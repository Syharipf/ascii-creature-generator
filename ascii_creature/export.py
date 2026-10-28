"""Slug validation, slugification, and atomic file writers."""

import json
import os
from pathlib import Path
import re
import tempfile
import unicodedata

from .errors import GeneratorError
from .runtime_template import module_source

ID_RE = re.compile(r"^[a-z][a-z0-9-]{0,47}$")


def validate_id(val: str) -> str:
    if not isinstance(val, str) or not ID_RE.match(val):
        raise GeneratorError("id must match ^[a-z][a-z0-9-]{0,47}$")
    return val


def slugify(name: str) -> str:
    if not name:
        return "creature"
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    text = re.sub(r"-+", "-", text)
    if not text or not text[0].isalpha():
        text = "creature-" + text if text else "creature"
    text = text[:48].rstrip("-")
    if not ID_RE.match(text):
        return "creature"
    return text


def _atomic_write(dest: Path, content: str) -> Path:
    parent = dest.parent
    parent.mkdir(parents=True, exist_ok=True)
    temp_file = tempfile.NamedTemporaryFile("w", dir=parent, delete=False, encoding="utf-8")
    try:
        temp_file.write(content)
        temp_file.flush()
        os.fsync(temp_file.fileno())
        temp_file.close()
        os.replace(temp_file.name, dest)
    except Exception:
        if os.path.exists(temp_file.name):
            try:
                os.unlink(temp_file.name)
            except OSError:
                pass
        raise
    return dest.resolve()


def write_outputs(component: dict, text: str, out_dir: str | Path) -> list[Path]:
    out_path = Path(out_dir).resolve()
    out_path.mkdir(parents=True, exist_ok=True)

    creature_id = validate_id(component.get("id", ""))
    mjs_content = module_source(component)
    json_content = json.dumps(component, indent=2, ensure_ascii=False) + "\n"

    mjs_path = _atomic_write(out_path / f"{creature_id}.mjs", mjs_content)
    json_path = _atomic_write(out_path / f"{creature_id}.json", json_content)
    txt_path = _atomic_write(out_path / f"{creature_id}.txt", text)

    return [mjs_path, json_path, txt_path]
