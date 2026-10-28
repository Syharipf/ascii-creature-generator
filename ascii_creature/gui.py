"""Localhost HTTP GUI server for ASCII creature generator."""

from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import traceback
import urllib.parse
import webbrowser

from .component import (
    DEFAULT_PARAMS,
    BuildResult,
    build,
    normalize_params,
)
from .errors import GeneratorError
from .export import slugify, validate_id, write_outputs
from .image import Source, load_source
from .runtime_template import module_source

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_JSON_BYTES = 64 * 1024
STATIC_DIR = Path(__file__).resolve().parent / "static"

CSP_HEADER = (
    "default-src 'self'; "
    "script-src 'self' blob:; "
    "style-src 'self'; "
    "img-src 'self' data:; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "base-uri 'none'; "
    "frame-ancestors 'none'"
)


class GuiState:
    def __init__(self):
        self.lock = threading.Lock()
        self.source: Source | None = None
        self.params: dict = dict(DEFAULT_PARAMS)
        self.result: BuildResult | None = None
        self.temp_dir = tempfile.TemporaryDirectory()

    def cleanup(self):
        self.temp_dir.cleanup()


class GuiServer(ThreadingHTTPServer):
    def __init__(self, server_address, RequestHandlerClass, state: GuiState, out_dir: str | Path):
        super().__init__(server_address, RequestHandlerClass)
        self.state = state
        self.out_dir = Path(out_dir).resolve()


class GuiRequestHandler(BaseHTTPRequestHandler):
    server: GuiServer

    def log_message(self, format, *args):
        # Silence default request logging in tests/headless
        pass

    def _set_headers(self, status: int, content_type: str):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", CSP_HEADER)
        self.end_headers()

    def _send_json(self, status: int, payload: dict):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._set_headers(status, "application/json; charset=utf-8")
        self.wfile.write(body)

    def _send_error(self, status: int, msg: str):
        self._send_json(status, {"error": msg})

    def _read_body(self, max_bytes: int) -> bytes | None:
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            self._send_error(400, "Invalid Content-Length")
            return None

        if length > max_bytes:
            self._send_error(413, f"Body exceeds maximum limit of {max_bytes} bytes")
            return None

        return self.rfile.read(length)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/":
            index_path = STATIC_DIR / "index.html"
            try:
                data = index_path.read_bytes()
                self._set_headers(200, "text/html; charset=utf-8")
                self.wfile.write(data)
            except OSError:
                self._send_error(500, "Cannot read index.html")
            return

        if path == "/static/app.js":
            js_path = STATIC_DIR / "app.js"
            try:
                data = js_path.read_bytes()
                self._set_headers(200, "text/javascript; charset=utf-8")
                self.wfile.write(data)
            except OSError:
                self._send_error(404, "Not found")
            return

        if path == "/static/style.css":
            css_path = STATIC_DIR / "style.css"
            try:
                data = css_path.read_bytes()
                self._set_headers(200, "text/css; charset=utf-8")
                self.wfile.write(data)
            except OSError:
                self._send_error(404, "Not found")
            return

        if path == "/api/state":
            state = self.server.state
            with state.lock:
                if state.source is None or state.result is None:
                    self._send_json(200, {"loaded": False})
                    return

                resp = {
                    "loaded": True,
                    "source": {
                        "name": state.source.name,
                        "width": state.source.orig_size[0],
                        "height": state.source.orig_size[1],
                    },
                    "params": state.params,
                    "stats": state.result.stats,
                    "creature": state.result.component,
                    "module": module_source(state.result.component),
                    "text": state.result.text,
                }
                self._send_json(200, resp)
            return

        self._send_error(404, "Not found")

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        state = self.server.state

        if path == "/api/upload":
            query = urllib.parse.parse_qs(parsed.query)
            raw_name = query.get("name", ["image.png"])[0]
            clean_name = Path(raw_name).name or "image.png"

            body = self._read_body(MAX_UPLOAD_BYTES)
            if body is None:
                return

            if not body:
                self._send_error(400, "Empty upload body")
                return

            temp_path = Path(state.temp_dir.name) / clean_name
            try:
                temp_path.write_bytes(body)
                src = load_source(temp_path)
            except GeneratorError as err:
                self._send_error(400, str(err))
                return
            except Exception as exc:
                traceback.print_exc()
                self._send_error(500, "Failed to ingest image")
                return

            stem_id = slugify(temp_path.stem)
            with state.lock:
                state.source = src
                req_params = dict(state.params)
                req_params["id"] = stem_id
                req_params["name"] = stem_id.replace("-", " ").title()
                state.params = normalize_params(req_params, fallback_id=stem_id)
                try:
                    res = build(src, state.params)
                    state.result = res
                except GeneratorError as err:
                    self._send_error(400, str(err))
                    return

                resp = {
                    "source": {
                        "name": src.name,
                        "width": src.orig_size[0],
                        "height": src.orig_size[1],
                    },
                    "params": state.params,
                    "stats": res.stats,
                    "creature": res.component,
                    "module": module_source(res.component),
                    "text": res.text,
                }
                self._send_json(200, resp)
            return

        if path == "/api/convert":
            body = self._read_body(MAX_JSON_BYTES)
            if body is None:
                return

            try:
                req_json = json.loads(body.decode("utf-8")) if body else {}
            except Exception:
                self._send_error(400, "Invalid JSON body")
                return

            with state.lock:
                if state.source is None:
                    self._send_error(400, "No image uploaded yet")
                    return

                new_params = normalize_params(req_json, fallback_id=state.params.get("id"))
                try:
                    res = build(state.source, new_params)
                    state.params = new_params
                    state.result = res
                except GeneratorError as err:
                    self._send_error(400, str(err))
                    return

                resp = {
                    "source": {
                        "name": state.source.name,
                        "width": state.source.orig_size[0],
                        "height": state.source.orig_size[1],
                    },
                    "params": state.params,
                    "stats": res.stats,
                    "creature": res.component,
                    "module": module_source(res.component),
                    "text": res.text,
                }
                self._send_json(200, resp)
            return

        if path == "/api/export":
            body = self._read_body(MAX_JSON_BYTES)
            if body is None:
                return

            try:
                req_json = json.loads(body.decode("utf-8")) if body else {}
            except Exception:
                self._send_error(400, "Invalid JSON body")
                return

            with state.lock:
                if state.source is None:
                    self._send_error(400, "No image uploaded yet")
                    return

                params_in = req_json.get("params", state.params)
                if "id" in req_json and req_json["id"]:
                    params_in["id"] = req_json["id"]
                if "name" in req_json and req_json["name"]:
                    params_in["name"] = req_json["name"]

                try:
                    norm = normalize_params(params_in, fallback_id=state.params.get("id"))
                    res = build(state.source, norm)
                    written = write_outputs(res.component, res.text, self.server.out_dir)
                except GeneratorError as err:
                    self._send_error(400, str(err))
                    return
                except Exception as exc:
                    traceback.print_exc()
                    self._send_error(500, "Export failed")
                    return

                files_info = [
                    {"path": str(p), "bytes": p.stat().st_size}
                    for p in written
                ]
                self._send_json(200, {"files": files_info})
            return

        self._send_error(404, "Not found")


def make_server(state: GuiState, out_dir: str | Path, port: int = 0) -> GuiServer:
    server = GuiServer(("127.0.0.1", port), GuiRequestHandler, state, out_dir)
    return server


def run_gui(path: str | None = None, out_dir: str = "out", port: int = 0, no_browser: bool = False):
    state = GuiState()
    if path:
        try:
            src = load_source(path)
            state.source = src
            stem_id = slugify(Path(path).stem)
            state.params = normalize_params(dict(DEFAULT_PARAMS), fallback_id=stem_id)
            state.result = build(src, state.params)
        except GeneratorError as exc:
            print(f"Error loading image: {exc}", file=sys.stderr)
            sys.exit(2)

    server = make_server(state, out_dir, port=port)
    actual_port = server.server_address[1]
    url = f"http://127.0.0.1:{actual_port}/"
    print(url, flush=True)

    if not no_browser:
        webbrowser.open(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        state.cleanup()
