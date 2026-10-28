"""Grid sampling, parameter normalization, text art, and build pipeline."""

from dataclasses import dataclass
import math
from pathlib import Path
from typing import NamedTuple

from . import VERSION
from .errors import GeneratorError
from .export import slugify, validate_id
from .image import Source, build_mask, crop_to_mask
from .motion import MOTION_PRESETS, POV_PRESETS

CELL_ASPECT = 2.0 / 3.0  # cw / ch, same ratio as ascii-ocean (12 / 18)
GLYPHS = "@%#*+=-:."      # dense -> sparse, component ink
TEXT_RAMP = " .:-=+*#%@"  # dark -> bright, plain-text export
DARK_INK = "#0e0f13"
LIGHT_INK = "#eef3fa"

DEFAULT_PARAMS = {
    "cols": 28,
    "tolerance": 32.0,
    "coverage": 0.40,
    "posterize": 16,
    "head_side": "left",
    "preset": "swim",
    "amplitude": 1.0,
    "speed": 0.55,
    "wavelength": 1.1,
    "bob": 0.35,
    "pov": "side",
    "pitch": 0.0,
    "roll": 0.15,
}


class BuildResult(NamedTuple):
    component: dict
    stats: dict
    text: str


def normalize_params(raw: dict | None, fallback_id: str | None = None) -> dict:
    raw = raw or {}
    params: dict = {}

    cols = int(raw.get("cols", DEFAULT_PARAMS["cols"]))
    params["cols"] = max(8, min(96, cols))

    tol = float(raw.get("tolerance", DEFAULT_PARAMS["tolerance"]))
    params["tolerance"] = max(0.0, min(160.0, tol))

    cov = float(raw.get("coverage", DEFAULT_PARAMS["coverage"]))
    params["coverage"] = max(0.05, min(0.95, cov))

    post = int(raw.get("posterize", DEFAULT_PARAMS["posterize"]))
    if post <= 0:
        params["posterize"] = 0
    else:
        params["posterize"] = max(2, min(128, post))

    head_side = str(raw.get("head_side", DEFAULT_PARAMS["head_side"])).lower()
    params["head_side"] = head_side if head_side in {"left", "right"} else "left"

    preset = str(raw.get("preset", DEFAULT_PARAMS["preset"])).lower()
    if preset not in MOTION_PRESETS:
        preset = "swim"
    params["preset"] = preset
    preset_vals = MOTION_PRESETS[preset]

    for key, (lo, hi) in [
        ("amplitude", (0.0, 3.0)),
        ("speed", (0.0, 2.0)),
        ("wavelength", (0.25, 3.0)),
        ("bob", (0.0, 2.0)),
    ]:
        val = raw[key] if key in raw and raw[key] is not None else preset_vals[key]
        params[key] = max(lo, min(hi, float(val)))


    pov = str(raw.get("pov", DEFAULT_PARAMS["pov"])).lower()
    if pov not in POV_PRESETS:
        pov = "side"
    params["pov"] = pov
    pov_vals = POV_PRESETS[pov]

    raw_pitch = raw.get("pitch")
    pitch = float(raw_pitch) if raw_pitch is not None else pov_vals["pitch"]
    params["pitch"] = max(-60.0, min(60.0, pitch))

    raw_roll = raw.get("roll")
    roll = float(raw_roll) if raw_roll is not None else pov_vals["roll"]
    params["roll"] = max(0.0, min(1.0, roll))
    raw_id = raw.get("id") or fallback_id or "creature"
    params["id"] = validate_id(str(raw_id))

    raw_name = raw.get("name")
    if raw_name is not None and str(raw_name).strip():
        params["name"] = str(raw_name).strip()[:80]
    else:
        params["name"] = params["id"].replace("-", " ").title()

    return params


def text(component: dict) -> str:
    cols = component["grid"]["cols"]
    rows = component["grid"]["rows"]
    cells = component["cells"]

    grid = [[" " for _ in range(cols)] for _ in range(rows)]
    for cell in cells:
        c = int(cell["u"] * cols)
        r = int(cell["v"] * rows)
        if 0 <= r < rows and 0 <= c < cols:
            hex_c = cell["bg"].lstrip("#")
            r_val = int(hex_c[0:2], 16)
            g_val = int(hex_c[2:4], 16)
            b_val = int(hex_c[4:6], 16)
            luma = (0.2126 * r_val + 0.7152 * g_val + 0.0722 * b_val) / 255.0
            ramp_idx = max(0, min(len(TEXT_RAMP) - 1, round(luma * (len(TEXT_RAMP) - 1))))
            grid[r][c] = TEXT_RAMP[ramp_idx]

    lines = ["".join(row).rstrip() for row in grid]
    return "\n".join(lines) + "\n"


def build(source: Source, raw_params: dict | None = None) -> BuildResult:
    stem_slug = slugify(Path(source.path).stem)
    norm = normalize_params(raw_params, fallback_id=stem_slug)

    mask = build_mask(source, norm["tolerance"])
    crop_rgb, crop_mask, bbox = crop_to_mask(source.rgb, mask)

    if norm["head_side"] == "right":
        crop_rgb = crop_rgb[:, ::-1]
        crop_mask = crop_mask[:, ::-1]

    crop_h, crop_w = crop_rgb.shape[:2]
    cols = norm["cols"]
    aspect = crop_h / crop_w
    rows = max(1, min(200, round(cols * aspect * CELL_ASPECT)))

    coverage = norm["coverage"]
    posterize = norm["posterize"]
    cells: list[dict] = []

    for r_idx in range(rows):
        y0 = math.floor(r_idx * crop_h / rows)
        y1 = max(y0 + 1, math.ceil((r_idx + 1) * crop_h / rows))
        for c_idx in range(cols):
            x0 = math.floor(c_idx * crop_w / cols)
            x1 = max(x0 + 1, math.ceil((c_idx + 1) * crop_w / cols))

            sub_mask = crop_mask[y0:y1, x0:x1]
            cov = float(sub_mask.mean())
            if cov < coverage:
                continue

            sub_rgb = crop_rgb[y0:y1, x0:x1]
            sel = sub_rgb[sub_mask]
            r_mean, g_mean, b_mean = sel.mean(axis=0)

            luma = (0.2126 * r_mean + 0.7152 * g_mean + 0.0722 * b_mean) / 255.0
            ink = DARK_INK if luma >= 0.5 else LIGHT_INK

            density = (1.0 - luma) if luma >= 0.5 else luma
            density *= 0.55 + 0.45 * cov
            glyph_idx = max(0, min(len(GLYPHS) - 1, round(density * (len(GLYPHS) - 1))))
            glyph = GLYPHS[glyph_idx]

            if posterize > 0:
                q = 255.0 / (posterize - 1)
                r_post = max(0, min(255, round(round(r_mean / q) * q)))
                g_post = max(0, min(255, round(round(g_mean / q) * q)))
                b_post = max(0, min(255, round(round(b_mean / q) * q)))
            else:
                r_post = max(0, min(255, round(r_mean)))
                g_post = max(0, min(255, round(g_mean)))
                b_post = max(0, min(255, round(b_mean)))

            bg_hex = f"#{r_post:02x}{g_post:02x}{b_post:02x}"
            u_coord = round((c_idx + 0.5) / cols, 5)
            v_coord = round((r_idx + 0.5) / rows, 5)

            cells.append({
                "u": u_coord,
                "v": v_coord,
                "g": glyph,
                "bg": bg_hex,
                "fg": ink,
            })

    component = {
        "format": "ascii-creature/1",
        "id": norm["id"],
        "name": norm["name"],
        "generator": f"ascii-creature-generator/{VERSION}",
        "headSide": norm["head_side"],
        "grid": {
            "cols": cols,
            "rows": rows,
            "cellAspect": round(CELL_ASPECT, 7),
        },
        "motion": {
            "preset": norm["preset"],
            "amplitude": norm["amplitude"],
            "speed": norm["speed"],
            "wavelength": norm["wavelength"],
            "bob": norm["bob"],
            "pov": norm["pov"],
            "pitch": norm["pitch"],
            "roll": norm["roll"],
        },
        "cells": cells,
    }

    stats = {
        "cells": len(cells),
        "dropped": (cols * rows) - len(cells),
        "cols": cols,
        "rows": rows,
        "bbox": [int(b) for b in bbox],
        "bg_mode": source.bg_mode,
        "bg_color": source.bg_color,
        "source": [int(s) for s in source.orig_size],
        "work": [int(w) for w in source.work_size],
    }

    txt_art = text(component)
    return BuildResult(component=component, stats=stats, text=txt_art)
