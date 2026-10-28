"""Comprehensive automated verification suite."""

import http.client
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import numpy as np
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from ascii_creature.component import BuildResult, build, normalize_params
from ascii_creature.errors import GeneratorError
from ascii_creature.export import write_outputs
from ascii_creature.gui import GuiState, make_server
from ascii_creature.image import crop_to_mask, load_source
from ascii_creature.motion import motion_nodes
from checks.fixture import make_fixtures

HEX_RE = re.compile(r"^#[0-9a-f]{6}$", re.I)


def assert_pass(condition: bool, step_name: str, detail: str = ""):
    if not condition:
        msg = f"FAIL: {step_name}"
        if detail:
            msg += f" ({detail})"
        print(msg, file=sys.stderr)
        sys.exit(1)
    print(f"PASS: {step_name}")


def main():
    print("=== ASCII Creature Generator Self-Check ===")
    tmp_root = Path(tempfile.mkdtemp(prefix="acg-selfcheck-"))

    try:
        # Fixtures
        fixtures_dir = tmp_root / "fixtures"
        fixtures = make_fixtures(fixtures_dir)
        fish_path = fixtures["fish"]
        cutout_path = fixtures["cutout"]
        empty_path = fixtures["empty"]

        # 1. fish.png core checks
        src_fish = load_source(fish_path)
        assert_pass(src_fish.bg_mode == "color", "fish.png color mode")
        assert_pass(src_fish.bg_color == "#2f6f8f", "fish.png background color #2f6f8f")

        res_fish: BuildResult = build(src_fish, {"id": "reef-fish", "name": "Reef Fish"})
        bbox = res_fish.stats["bbox"]
        bbox_ok = (
            abs(bbox[0] - 96) <= 3
            and abs(bbox[1] - 120) <= 3
            and abs(bbox[2] - 470) <= 3
            and abs(bbox[3] - 300) <= 3
        )
        assert_pass(bbox_ok, "fish.png bbox within +-3px of (96,120,470,300)", f"got {bbox}")
        assert_pass(
            res_fish.stats["cols"] == 28 and res_fish.stats["rows"] == 9,
            "fish.png default grid 28x9",
            f"got {res_fish.stats['cols']}x{res_fish.stats['rows']}",
        )
        assert_pass(
            res_fish.stats["cells"] > 120,
            "fish.png > 120 kept cells",
            f"got {res_fish.stats['cells']}",
        )

        all_uv_valid = True
        all_colors_valid = True
        all_glyphs_valid = True
        for c in res_fish.component["cells"]:
            if not (0.0 <= c["u"] <= 1.0 and 0.0 <= c["v"] <= 1.0):
                all_uv_valid = False
            if not (HEX_RE.match(c["bg"]) and HEX_RE.match(c["fg"])):
                all_colors_valid = False
            if len(c["g"]) != 1:
                all_glyphs_valid = False

        assert_pass(all_uv_valid, "fish.png all cell u/v in (0,1)")
        assert_pass(all_colors_valid, "fish.png all cell colors hex")
        assert_pass(all_glyphs_valid, "fish.png all glyphs single character")

        # 2. cutout.png checks
        src_cutout = load_source(cutout_path)
        assert_pass(src_cutout.bg_mode == "alpha", "cutout.png alpha mode")
        res_cut_tol10 = build(src_cutout, {"id": "cutout", "tolerance": 10.0})
        res_cut_tol80 = build(src_cutout, {"id": "cutout", "tolerance": 80.0})
        assert_pass(
            len(res_cut_tol10.component["cells"]) == len(res_cut_tol80.component["cells"]),
            "cutout.png tolerance invariance on alpha",
        )

        # 3. empty.png check
        src_empty = load_source(empty_path)
        threw_empty = False
        err_msg = ""
        try:
            build(src_empty, {"id": "empty", "tolerance": 32.0})
        except GeneratorError as err:
            threw_empty = True
            err_msg = str(err)
        assert_pass(
            threw_empty and "No foreground found" in err_msg,
            "empty.png raises GeneratorError('No foreground found')",
        )

        # 4. Flip check (eye cell position)
        res_left = build(src_fish, {"head_side": "left"})
        res_right = build(src_fish, {"head_side": "right"})

        def find_eye_cell(cells):
            darkest = None
            min_luma = 999.0
            for c in cells:
                # Eye is around vertical middle (v in 0.2..0.6)
                if 0.2 <= c["v"] <= 0.6:
                    hx = c["bg"].lstrip("#")
                    r, g, b = int(hx[0:2], 16), int(hx[2:4], 16), int(hx[4:6], 16)
                    luma = 0.2126 * r + 0.7152 * g + 0.0722 * b
                    if luma < min_luma:
                        min_luma = luma
                        darkest = c
            return darkest

        eye_left = find_eye_cell(res_left.component["cells"])
        eye_right = find_eye_cell(res_right.component["cells"])
        assert_pass(eye_left is not None and eye_left["u"] < 0.25, "flip head_side=left eye u < 0.25", f"u={eye_left['u'] if eye_left else None}")
        assert_pass(eye_right is not None and eye_right["u"] > 0.75, "flip head_side=right eye u > 0.75", f"u={eye_right['u'] if eye_right else None}")

        # 5. Posterize check
        res_post4 = build(src_fish, {"posterize": 4})
        res_post16 = build(src_fish, {"posterize": 16})
        res_post0 = build(src_fish, {"posterize": 0})
        colors4 = len(set(c["bg"] for c in res_post4.component["cells"]))
        colors16 = len(set(c["bg"] for c in res_post16.component["cells"]))
        colors0 = len(set(c["bg"] for c in res_post0.component["cells"]))
        assert_pass(colors4 < colors16, "posterize 4 fewer colors than 16", f"{colors4} < {colors16}")
        assert_pass(colors0 >= colors16, "posterize 0 preserves more colors", f"{colors0} >= {colors16}")

        # 6. Reproducibility check
        res_a = build(src_fish, {"id": "fish-dup", "cols": 28, "tolerance": 32.0})
        res_b = build(src_fish, {"id": "fish-dup", "cols": 28, "tolerance": 32.0})
        json_a = json.dumps(res_a.component, sort_keys=True)
        json_b = json.dumps(res_b.component, sort_keys=True)
        out_dir_a = tmp_root / "out_a"
        out_dir_b = tmp_root / "out_b"
        paths_a = write_outputs(res_a.component, res_a.text, out_dir_a)
        paths_b = write_outputs(res_b.component, res_b.text, out_dir_b)
        assert_pass(json_a == json_b, "two builds produce identical component JSON")
        assert_pass(paths_a[0].read_bytes() == paths_b[0].read_bytes(), "two builds produce identical .mjs bytes")

        # 7. Output files validation
        out_dir_main = tmp_root / "export"
        written = write_outputs(res_fish.component, res_fish.text, out_dir_main)
        mjs_file, json_file, txt_file = written

        read_json = json.loads(json_file.read_text("utf-8"))
        assert_pass(read_json == res_fish.component, ".json equals built component")

        mjs_text = mjs_file.read_text("utf-8")
        mjs_valid = (
            mjs_text.startswith("export const creature =")
            and "createAppearance" in mjs_text
            and "motionNodes" in mjs_text
            and "drawCreature" in mjs_text
        )
        assert_pass(mjs_valid, ".mjs starts with export const creature = and contains functions")

        txt_lines = txt_file.read_text("utf-8").splitlines()
        rows_exp = res_fish.stats["rows"]
        cols_exp = res_fish.stats["cols"]
        txt_valid = (
            len(txt_lines) == rows_exp
            and all(len(line) <= cols_exp for line in txt_lines)
            and any(any(ch != " " for ch in line) for line in txt_lines)
        )
        assert_pass(txt_valid, ".txt matches rows/cols bounds with non-space art")

        # 8. Motion parity
        exp_motion_path = tmp_root / "expected_motion.json"
        time_test = 0.85
        length_test = 260.0
        py_nodes_raw = motion_nodes(res_fish.component["motion"], time_test, length_test)
        py_flat = [float(np.float32(v)) for pt in py_nodes_raw for v in pt]
        exp_motion_path.write_text(
            json.dumps({"time": time_test, "length": length_test, "nodes": py_flat})
        )

        p_motion = subprocess.run(
            ["node", str(REPO_ROOT / "checks" / "motion_check.mjs"), str(mjs_file), str(exp_motion_path)],
            capture_output=True,
            text=True,
        )
        assert_pass(
            p_motion.returncode == 0 and "PASS: motion parity" in p_motion.stdout,
            "motion parity check",
            p_motion.stderr.strip() or p_motion.stdout.strip(),
        )

        # 9. Runtime schema
        p_comp = subprocess.run(
            ["node", str(REPO_ROOT / "checks" / "component_check.mjs"), str(mjs_file)],
            capture_output=True,
            text=True,
        )
        assert_pass(
            p_comp.returncode == 0 and "PASS: component runtime" in p_comp.stdout,
            "component runtime schema check",
            p_comp.stderr.strip() or p_comp.stdout.strip(),
        )

        # 9b. POV normalization & 2.5D perspective foreshortening
        norm_side = normalize_params({"pov": "side"})
        norm_top = normalize_params({"pov": "top"})
        norm_iso = normalize_params({"pov": "isometric"})
        norm_bot = normalize_params({"pov": "bottom"})
        pov_ok = (
            norm_side["pitch"] == 0.0 and norm_side["roll"] == 0.15 and
            norm_top["pitch"] == 55.0 and norm_top["roll"] == 0.35 and
            norm_iso["pitch"] == 30.0 and norm_iso["roll"] == 0.25 and
            norm_bot["pitch"] == -30.0 and norm_bot["roll"] == 0.20
        )
        assert_pass(pov_ok, "normalize_params sets correct POV presets")

        node_pov_script = f"""
import {{ drawCreature }} from "{mjs_file.resolve().as_uri()}";
let scales0 = [];
let scales60 = [];
const makeCtx = (arr) => ({{
  save() {{}}, restore() {{}}, translate() {{}}, rotate() {{}},
  scale(sx, sy) {{ arr.push(sy); }},
  fillRect() {{}}, fillText() {{}}
}});
drawCreature(makeCtx(scales0), {{ length: 200, time: 0, pitch: 0, roll: 0 }});
drawCreature(makeCtx(scales60), {{ length: 200, time: 0, pitch: 60, roll: 0 }});

let minY0 = Infinity, maxY0 = -Infinity;
let minY60 = Infinity, maxY60 = -Infinity;
const makeFallback = (cb) => ({{
  save() {{}}, restore() {{}}, translate() {{}}, rotate() {{}},
  fillRect(x, y, w, h) {{ cb(y, h); }},
  fillText() {{}}
}});
drawCreature(makeFallback((y, h) => {{ minY0 = Math.min(minY0, y); maxY0 = Math.max(maxY0, y + h); }}), {{ length: 200, time: 0, pitch: 0, roll: 0 }});
drawCreature(makeFallback((y, h) => {{ minY60 = Math.min(minY60, y); maxY60 = Math.max(maxY60, y + h); }}), {{ length: 200, time: 0, pitch: 60, roll: 0 }});

const s0 = scales0[0];
const s60 = scales60[0];
const h0 = maxY0 - minY0;
const h60 = maxY60 - minY60;
if (Math.abs(s0 - 1.0) < 0.05 && Math.abs(s60 - 0.5) < 0.05 && h60 < h0 * 0.7) {{
  console.log("PASS: pitch foreshortening");
}} else {{
  console.error(`s0=${{s0}}, s60=${{s60}}, h0=${{h0}}, h60=${{h60}}`);
  process.exit(1);
}}
"""
        p_pov = subprocess.run(["node", "--input-type=module", "-e", node_pov_script], capture_output=True, text=True)
        assert_pass(
            p_pov.returncode == 0 and "PASS: pitch foreshortening" in p_pov.stdout,
            "drawCreature with pitch alters rendered vertical extent",
            p_pov.stderr.strip() or p_pov.stdout.strip(),
        )

        # 10. HTTP API in-process
        gui_out = tmp_root / "gui_out"
        gui_state = GuiState()
        gui_server = make_server(gui_state, gui_out, port=0)
        port = gui_server.server_address[1]
        srv_thread = threading.Thread(target=gui_server.serve_forever, daemon=True)
        srv_thread.start()

        time.sleep(0.05)
        conn = http.client.HTTPConnection("127.0.0.1", port)

        # Upload
        fish_bytes = fish_path.read_bytes()
        conn.request("POST", "/api/upload?name=fish.png", body=fish_bytes)
        resp_up = conn.getresponse()
        up_data = json.loads(resp_up.read().decode("utf-8"))
        assert_pass(resp_up.status == 200 and "creature" in up_data, "HTTP API /api/upload 200")

        # Convert
        conn.request("POST", "/api/convert", body=json.dumps({"cols": 36}), headers={"Content-Type": "application/json"})
        resp_conv = conn.getresponse()
        conv_data = json.loads(resp_conv.read().decode("utf-8"))
        assert_pass(resp_conv.status == 200 and conv_data["params"]["cols"] == 36, "HTTP API /api/convert 200 cols=36")

        # Export
        conn.request(
            "POST",
            "/api/export",
            body=json.dumps({"id": "gui-creature", "name": "GUI Creature"}),
            headers={"Content-Type": "application/json"},
        )
        resp_exp = conn.getresponse()
        exp_data = json.loads(resp_exp.read().decode("utf-8"))
        assert_pass(
            resp_exp.status == 200 and len(exp_data.get("files", [])) == 3,
            "HTTP API /api/export 200 3 files",
        )
        assert_pass((gui_out / "gui-creature.mjs").exists(), "HTTP API export files exist on disk")

        # Error handling: bad id
        conn.request(
            "POST",
            "/api/export",
            body=json.dumps({"id": "BAD ID WITH SPACES"}),
            headers={"Content-Type": "application/json"},
        )
        resp_err_id = conn.getresponse()
        resp_err_id.read()
        assert_pass(resp_err_id.status == 400, "HTTP API bad id returns 400")

        # Error handling: body too large (>25MB)
        conn.request(
            "POST",
            "/api/upload?name=huge.png",
            body=b"A" * 64,
            headers={"Content-Length": str(28 * 1024 * 1024)},
        )
        resp_huge = conn.getresponse()
        resp_huge.read()
        assert_pass(resp_huge.status == 413, "HTTP API oversized upload returns 413")

        conn.close()
        gui_server.shutdown()
        gui_server.server_close()
        gui_state.cleanup()

        # 11. QML render: Animal in isolation
        ocean_copy = tmp_root / "ascii-ocean"
        shutil.copytree(str(REPO_ROOT.parent / "ascii-ocean"), str(ocean_copy))

        ocean_creatures = ocean_copy / "package" / "contents" / "ui" / "creatures"
        ocean_creatures.mkdir(parents=True, exist_ok=True)
        shutil.copy(str(mjs_file), str(ocean_creatures / f"{res_fish.component['id']}.mjs"))

        preview_animal_qml = ocean_copy / "checks" / "creature-preview.qml"
        preview_animal_qml.write_text(f"""import QtQuick
import "../package/contents/ui" as OceanUI
import "../package/contents/ui/creatures/{res_fish.component['id']}.mjs" as C

Item {{
    id: root
    width: 600
    height: 500

    Rectangle {{
        anchors.fill: parent
        color: "#0a1118"
    }}

    Item {{
        id: container
        x: 300
        y: 250
        rotation: 180

        OceanUI.Animal {{
            id: animalComp
            animal: ({{
                appearance: C.createAppearance(300),
                nodes: C.motionNodes(0.4, 300),
                depth: 1.0
            }})
        }}
    }}

    property int elapsedTicks: 0
    Timer {{
        interval: 50
        repeat: true
        running: true
        onTriggered: {{
            animalComp.epoch++;
            root.elapsedTicks++;
            if (root.elapsedTicks >= 14) {{
                running = false;
                root.grabToImage(function(result) {{
                    var ok = result.saveToFile("/tmp/ascii-creature-ocean-animal.png");
                    Qt.quit();
                }});
            }}
        }}
    }}
}}
""")

        env = dict(os.environ)
        env["QT_FORCE_STDERR_LOGGING"] = "1"
        env["QT_QPA_PLATFORM"] = "offscreen"

        animal_out_png = Path("/tmp/ascii-creature-ocean-animal.png")
        if animal_out_png.exists():
            animal_out_png.unlink()

        res_qml_animal = subprocess.run(
            ["qml6", str(preview_animal_qml)],
            env=env,
            capture_output=True,
            text=True,
            timeout=15,
        )
        if not animal_out_png.exists():
            env["QT_QUICK_BACKEND"] = "software"
            res_qml_animal = subprocess.run(
                ["qml6", str(preview_animal_qml)],
                env=env,
                capture_output=True,
                text=True,
                timeout=15,
            )

        assert_pass(animal_out_png.exists(), "QML animal preview generated PNG")
        if animal_out_png.exists():
            im_anim = Image.open(animal_out_png)
            arr_anim = np.array(im_anim)
            bg_col = np.array([10, 17, 24], dtype=np.uint8)
            diff_anim = (np.abs(arr_anim[:, :, :3].astype(int) - bg_col.astype(int)).sum(axis=2) > 10).sum()
            print(f"Animal snapshot dimensions: {im_anim.size}, differing pixels: {diff_anim}")
            assert_pass(diff_anim > 2000, "QML animal preview > 2,000 pixels differing from background")

        # 12. Full ocean scene integration
        engine_path = ocean_copy / "package" / "contents" / "ui" / "engine.mjs"
        engine_txt = engine_path.read_text("utf-8")
        creature_id = res_fish.component["id"]

        # Mechanical patch with assertion of unique replacements
        m1 = 'import { Ambience } from "./ambience.mjs";'
        assert engine_txt.count(m1) == 1, f"Marker 1 count {engine_txt.count(m1)}"
        engine_txt = engine_txt.replace(m1, f'{m1}\nimport * as CUSTOM from "./creatures/{creature_id}.mjs";')

        m2 = '"kraken"\n];'
        assert engine_txt.count(m2) == 1, f"Marker 2 count {engine_txt.count(m2)}"
        engine_txt = engine_txt.replace(m2, f'"kraken",\n  "{creature_id}"\n];')

        m3 = '    case "all":'
        assert engine_txt.count(m3) == 1, f"Marker 3 count {engine_txt.count(m3)}"
        spec_block = f"""    case "{creature_id}":
      return [
        {{ kind: "{creature_id}", size: 1.0 }},
        {{ kind: "{creature_id}", size: 0.88 }},
        {{ kind: "{creature_id}", size: 0.78 }},
        {{ kind: "{creature_id}", size: 0.68 }}
      ];\n"""
        engine_txt = engine_txt.replace(m3, spec_block + m3)

        m4 = 'app = animalAppearance(kind, length, this.cellWidth, this.cellHeight);'
        assert engine_txt.count(m4) == 1, f"Marker 4 count {engine_txt.count(m4)}"
        app_block = """app = kind === CUSTOM.creature.id
      ? CUSTOM.createAppearance(length)
      : animalAppearance(kind, length, this.cellWidth, this.cellHeight);"""
        engine_txt = engine_txt.replace(m4, app_block)

        engine_path.write_text(engine_txt, "utf-8")
        assert_pass(True, "patched temporary ascii-ocean copy")

        # Scene preview QML
        scene_preview_qml = ocean_copy / "checks" / "scene-preview.qml"
        scene_preview_qml.write_text(f"""import QtQuick
import "../package/contents/ui" as UI

Item {{
    id: root
    width: 960
    height: 600

    UI.Ocean {{
        id: ocean
        anchors.fill: parent
        sharkKind: "{creature_id}"
        previewPhase: "day"
        previewWeather: "clear"
        showClouds: false
        showRain: false
        showWaves: false
        pauseOnAppOpen: false
    }}

    property int frameCount: 0
    Timer {{
        interval: 16
        repeat: true
        running: true
        onTriggered: {{
            ocean.advanceFrame(1.0 / 30.0);
            root.frameCount++;
            if (root.frameCount >= 45) {{
                running = false;
                ocean.grabToImage(function(result) {{
                    var ok = result.saveToFile("/tmp/ascii-creature-ocean-scene.png");
                    Qt.quit();
                }});
            }}
        }}
    }}
}}
""")

        scene_out_png = Path("/tmp/ascii-creature-ocean-scene.png")
        if scene_out_png.exists():
            scene_out_png.unlink()

        res_qml_scene = subprocess.run(
            ["qml6", str(scene_preview_qml)],
            env=env,
            capture_output=True,
            text=True,
            timeout=20,
        )
        if not scene_out_png.exists():
            env["QT_QUICK_BACKEND"] = "software"
            res_qml_scene = subprocess.run(
                ["qml6", str(scene_preview_qml)],
                env=env,
                capture_output=True,
                text=True,
                timeout=20,
            )

        assert_pass(scene_out_png.exists(), "QML scene preview generated PNG")
        if scene_out_png.exists():
            im_scene = Image.open(scene_out_png)
            arr_scene = np.array(im_scene)
            bg_corner = arr_scene[0, 0, :3].astype(int)
            diff_scene = (np.abs(arr_scene[:, :, :3].astype(int) - bg_corner).sum(axis=2) > 15).sum()
            print(f"Scene snapshot dimensions: {im_scene.size}, differing pixels: {diff_scene}")
            assert_pass(diff_scene > 2000, "QML scene preview non-background coverage > 2,000 pixels")

        # 13. Engine integration check
        p_engine = subprocess.run(
            [
                "node",
                str(REPO_ROOT / "checks" / "consumer_engine_check.mjs"),
                "--engine",
                str(engine_path),
                "--kind",
                creature_id,
            ],
            capture_output=True,
            text=True,
        )
        assert_pass(
            p_engine.returncode == 0 and "PASS: consumer engine integration" in p_engine.stdout,
            "consumer engine integration check",
            p_engine.stderr.strip() or p_engine.stdout.strip(),
        )

        # 14. ascii-sky note
        print("SKIP sky integration: ../ascii-sky engine does not expose getSharkSpecs/getAppearance (custom contract required)")

        print("=== ALL CHECKS PASSED ===")

    finally:
        shutil.rmtree(tmp_root)


if __name__ == "__main__":
    main()
