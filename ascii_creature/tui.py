"""Interactive curses TUI for ASCII creature tuning and preview."""

import curses
import math
from pathlib import Path
import sys
import time

from .component import (
    DEFAULT_PARAMS,
    BuildResult,
    build,
    normalize_params,
)
from .errors import GeneratorError
from .export import slugify, validate_id, write_outputs
from .image import load_source
from .motion import MOTION_PRESETS, POV_PRESETS, motion_nodes

POSTERIZE_STEPS = [0, 4, 8, 16, 32, 64]
PRESET_NAMES = list(MOTION_PRESETS.keys())
POV_NAMES = list(POV_PRESETS.keys())

def _rgb_from_hex(hex_str: str) -> tuple[int, int, int]:
    clean = hex_str.lstrip("#")
    return int(clean[0:2], 16), int(clean[2:4], 16), int(clean[4:6], 16)


def _rgb_to_xterm256(r: int, g: int, b: int) -> int:
    if abs(r - g) < 8 and abs(g - b) < 8 and abs(r - b) < 8:
        gray = round((r + g + b) / 3)
        if gray < 8:
            return 16
        if gray > 248:
            return 231
        return 232 + max(0, min(23, round((gray - 8) / 10)))
    qr = max(0, min(5, round(r / 51)))
    qg = max(0, min(5, round(g / 51)))
    qb = max(0, min(5, round(b / 51)))
    return 16 + 36 * qr + 6 * qg + qb


def _rgb_to_basic8(r: int, g: int, b: int) -> tuple[int, bool]:
    # Returns (curses_color, is_bold)
    luma = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255.0
    bold = luma > 0.5
    cr = 1 if r >= 100 else 0
    cg = 1 if g >= 100 else 0
    cb = 1 if b >= 100 else 0
    code = (cr << 0) | (cg << 1) | (cb << 2)
    # Map (r,g,b) bits to curses COLOR constants
    color_map = {
        0: curses.COLOR_BLACK,
        1: curses.COLOR_RED,
        2: curses.COLOR_GREEN,
        3: curses.COLOR_YELLOW,
        4: curses.COLOR_BLUE,
        5: curses.COLOR_MAGENTA,
        6: curses.COLOR_CYAN,
        7: curses.COLOR_WHITE,
    }
    return color_map.get(code, curses.COLOR_WHITE), bold


class ColorManager:
    def __init__(self, has_256: bool):
        self.has_256 = has_256
        self.pairs: dict[tuple[int, int], int] = {}
        self.next_pair = 1
        self.max_pairs = getattr(curses, "COLOR_PAIRS", 256)

    def get_attr(self, fg_hex: str, bg_hex: str) -> int:
        fr, fg, fb = _rgb_from_hex(fg_hex)
        br, bg, bb = _rgb_from_hex(bg_hex)

        bold = False
        if self.has_256:
            fg_idx = _rgb_to_xterm256(fr, fg, fb)
            bg_idx = _rgb_to_xterm256(br, bg, bb)
        else:
            fg_idx, bold = _rgb_to_basic8(fr, fg, fb)
            bg_idx, _ = _rgb_to_basic8(br, bg, bb)

        pair_key = (fg_idx, bg_idx)
        if pair_key in self.pairs:
            pair_num = self.pairs[pair_key]
        elif self.next_pair < self.max_pairs:
            try:
                curses.init_pair(self.next_pair, fg_idx, bg_idx)
                self.pairs[pair_key] = self.next_pair
                pair_num = self.next_pair
                self.next_pair += 1
            except curses.error:
                pair_num = 0
        else:
            pair_num = 0

        attr = curses.color_pair(pair_num)
        if bold:
            attr |= curses.A_BOLD
        return attr


def _prompt_export(stdscr, y: int, max_w: int, default_id: str) -> str | None:
    curses.curs_set(1)
    prompt = "Export ID: "
    val = list(default_id)
    pos = len(val)

    while True:
        stdscr.move(y, 0)
        stdscr.clrtoeol()
        stdscr.addstr(y, 0, prompt)
        line_str = "".join(val)
        display_str = line_str[: max_w - len(prompt) - 2]
        stdscr.addstr(y, len(prompt), display_str)
        stdscr.move(y, len(prompt) + min(pos, len(display_str)))
        stdscr.refresh()

        ch = stdscr.getch()
        if ch == 27:  # Esc
            curses.curs_set(0)
            return None
        elif ch in (10, 13, curses.KEY_ENTER):
            slug = "".join(val).strip()
            try:
                validate_id(slug)
                curses.curs_set(0)
                return slug
            except GeneratorError as err:
                stdscr.move(y, 0)
                stdscr.clrtoeol()
                err_msg = f"Error: {err} (press any key)"
                stdscr.addstr(y, 0, err_msg[: max_w - 1], curses.A_BOLD)
                stdscr.refresh()
                stdscr.getch()
        elif ch in (curses.KEY_BACKSPACE, 127, 8):
            if pos > 0:
                pos -= 1
                val.pop(pos)
        elif ch == curses.KEY_LEFT:
            pos = max(0, pos - 1)
        elif ch == curses.KEY_RIGHT:
            pos = min(len(val), pos + 1)
        elif 32 <= ch <= 126:
            val.insert(pos, chr(ch))
            pos += 1


def _tui_loop(stdscr, source_path: str, out_dir: str):
    curses.curs_set(0)
    curses.start_color()
    try:
        curses.use_default_colors()
    except curses.error:
        pass
    stdscr.keypad(True)
    stdscr.timeout(80)

    has_256 = curses.COLORS >= 256
    cm = ColorManager(has_256)

    try:
        source = load_source(source_path)
    except GeneratorError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(2)

    stem_id = slugify(Path(source_path).stem)
    params = normalize_params(dict(DEFAULT_PARAMS), fallback_id=stem_id)

    try:
        result: BuildResult = build(source, params)
    except GeneratorError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(2)

    status_msg = "Ready. Press 'e' to export, 'q' to quit."
    status_is_error = False
    anim_t = 0.0
    last_clock = time.monotonic()

    while True:
        now = time.monotonic()
        dt = now - last_clock
        last_clock = now
        anim_t += dt

        lines, cols_term = stdscr.getmaxyx()
        stdscr.erase()

        if lines < 24 or cols_term < 80:
            msg = "Terminal too small (need 80x24)"
            stdscr.addstr(lines // 2, max(0, (cols_term - len(msg)) // 2), msg)
            stdscr.refresh()
            ch = stdscr.getch()
            if ch == ord("q"):
                break
            continue

        # Header
        header = f" ASCII CREATURE GENERATOR — {Path(source.path).name} ({source.work_size[0]}x{source.work_size[1]}) "
        stdscr.addstr(0, 0, header[: cols_term - 1], curses.A_REVERSE)

        # Footer help
        footer = " [q]uit [e]xport [r]eset [f]lip [d/D]cols [t/T]tol [c/C]cov [p/P]post [m]preset [v/V]pov [a/A]amp [s/S]spd [w/W]wav [b/B]bob "
        if lines - 1 < lines:
            stdscr.addstr(lines - 1, 0, footer[: cols_term - 1], curses.A_DIM)

        # Status row
        status_row = lines - 2
        status_attr = curses.A_BOLD if status_is_error else curses.A_NORMAL
        stdscr.addstr(status_row, 0, status_msg[: cols_term - 1], status_attr)

        # Sidebar
        sidebar_w = 30
        sidebar_x = cols_term - sidebar_w
        preview_w = sidebar_x - 1
        preview_h = lines - 3

        # Vertical divider
        for r in range(1, lines - 2):
            try:
                stdscr.addch(r, sidebar_x - 1, curses.ACS_VLINE)
            except curses.error:
                pass

        # Draw sidebar entries
        sb_lines = [
            f"ID: {params['id'][:18]}",
            f"Head side: {params['head_side']}",
            f"Grid: {result.stats['cols']}x{result.stats['rows']}",
            f"Cells: {result.stats['cells']} (drop {result.stats['dropped']})",
            f"Tolerance: {params['tolerance']:.1f}",
            f"Coverage: {params['coverage']:.2f}",
            f"Posterize: {params['posterize']}",
            "--- Motion ---",
            f"Preset: {params['preset']}",
            f"POV: {params['pov']} ({params['pitch']:.0f}°)",
            f"Roll: {params['roll']:.2f}",
            f"Amplitude: {params['amplitude']:.2f}",
            f"Speed: {params['speed']:.2f}",
            f"Wavelength: {params['wavelength']:.2f}",
            f"Bob: {params['bob']:.2f}",
            "--- Source ---",
            f"Mode: {result.stats['bg_mode']}",
            f"BG: {result.stats['bg_color'] or 'alpha'}",
            f"Work: {result.stats['work'][0]}x{result.stats['work'][1]}",
        ]
        for idx, text_line in enumerate(sb_lines):
            row_pos = 2 + idx
            if row_pos < lines - 2:
                try:
                    stdscr.addstr(row_pos, sidebar_x + 1, text_line[: sidebar_w - 2])
                except curses.error:
                    pass

        # Preview area: centered, animated
        comp = result.component
        grid_cols = comp["grid"]["cols"]
        grid_rows = comp["grid"]["rows"]

        pitch_scale = max(0.2, math.cos(math.radians(params["pitch"])))

        stride = max(1, math.ceil(grid_cols / preview_w), math.ceil((grid_rows * pitch_scale) / preview_h))
        disp_cols = grid_cols // stride
        disp_rows = max(1, round(grid_rows * pitch_scale)) // stride

        virt_len = grid_cols * 10.0
        cell_h = 15.0
        nodes = motion_nodes(comp["motion"], anim_t, virt_len)

        # Map nodes to column offsets with banking roll
        col_dy: list[int] = []
        wav = max(0.25, float(params.get("wavelength", 1.1)))
        speed = float(params.get("speed", 0.55))
        roll = float(params.get("roll", 0.15))
        for c in range(grid_cols):
            s = (c + 0.5) / grid_cols
            node_idx = s * 19.0
            k = min(18, max(0, int(node_idx)))
            f = node_idx - k
            y_disp = nodes[k][1] * (1.0 - f) + nodes[k + 1][1] * f
            roll_offset = roll * math.sin(2.0 * math.pi * (s / wav - speed * anim_t)) * (cell_h * 0.4)
            col_dy.append(round((y_disp + roll_offset) / cell_h))

        offset_x = max(0, (preview_w - disp_cols) // 2)
        offset_y = max(1, (preview_h - disp_rows) // 2 + 1)

        # Render cells into preview
        for cell in comp["cells"]:
            orig_c = int(cell["u"] * grid_cols)
            orig_r = int(cell["v"] * grid_rows)
            c_disp = orig_c // stride
            r_disp = round(orig_r * pitch_scale) // stride

            dy = col_dy[orig_c] if 0 <= orig_c < len(col_dy) else 0
            draw_x = offset_x + c_disp
            draw_y = offset_y + r_disp + dy

            if 0 <= draw_x < preview_w and 1 <= draw_y < lines - 2:
                attr = cm.get_attr(cell["fg"], cell["bg"])
                try:
                    stdscr.addch(draw_y, draw_x, cell["g"], attr)
                except curses.error:
                    pass

        stdscr.refresh()

        ch = stdscr.getch()
        if ch == -1:
            continue
        if ch == ord("q"):
            break

        # Handle parameter keys
        need_rebuild = False
        new_params = dict(params)

        if ch == ord("f"):
            new_params["head_side"] = "right" if params["head_side"] == "left" else "left"
            need_rebuild = True
        elif ch == ord("d"):
            new_params["cols"] = max(8, params["cols"] - 2)
            need_rebuild = True
        elif ch == ord("D"):
            new_params["cols"] = min(96, params["cols"] + 2)
            need_rebuild = True
        elif ch == ord("t"):
            new_params["tolerance"] = max(0.0, params["tolerance"] - 4.0)
            need_rebuild = True
        elif ch == ord("T"):
            new_params["tolerance"] = min(160.0, params["tolerance"] + 4.0)
            need_rebuild = True
        elif ch == ord("c"):
            new_params["coverage"] = max(0.05, round(params["coverage"] - 0.05, 2))
            need_rebuild = True
        elif ch == ord("C"):
            new_params["coverage"] = min(0.95, round(params["coverage"] + 0.05, 2))
            need_rebuild = True
        elif ch in (ord("p"), ord("P")):
            cur_post = params["posterize"]
            if ch == ord("p"):
                idx = (POSTERIZE_STEPS.index(cur_post) - 1) if cur_post in POSTERIZE_STEPS else 0
            else:
                idx = (POSTERIZE_STEPS.index(cur_post) + 1) if cur_post in POSTERIZE_STEPS else 0
            new_params["posterize"] = POSTERIZE_STEPS[idx % len(POSTERIZE_STEPS)]
            need_rebuild = True
        elif ch == ord("m"):
            cur_idx = PRESET_NAMES.index(params["preset"]) if params["preset"] in PRESET_NAMES else 0
            next_preset = PRESET_NAMES[(cur_idx + 1) % len(PRESET_NAMES)]
            new_params["preset"] = next_preset
            for k, val in MOTION_PRESETS[next_preset].items():
                new_params[k] = val
            need_rebuild = True
        elif ch in (ord("v"), ord("V")):
            cur_idx = POV_NAMES.index(params["pov"]) if params["pov"] in POV_NAMES else 0
            if ch == ord("v"):
                next_pov = POV_NAMES[(cur_idx + 1) % len(POV_NAMES)]
            else:
                next_pov = POV_NAMES[(cur_idx - 1) % len(POV_NAMES)]
            new_params["pov"] = next_pov
            new_params["pitch"] = POV_PRESETS[next_pov]["pitch"]
            new_params["roll"] = POV_PRESETS[next_pov]["roll"]
            need_rebuild = True
        elif ch == ord("a"):
            new_params["amplitude"] = max(0.0, round(params["amplitude"] - 0.1, 2))
            need_rebuild = True
        elif ch == ord("A"):
            new_params["amplitude"] = min(3.0, round(params["amplitude"] + 0.1, 2))
            need_rebuild = True
        elif ch == ord("s"):
            new_params["speed"] = max(0.0, round(params["speed"] - 0.05, 2))
            need_rebuild = True
        elif ch == ord("S"):
            new_params["speed"] = min(2.0, round(params["speed"] + 0.05, 2))
            need_rebuild = True
        elif ch == ord("w"):
            new_params["wavelength"] = max(0.25, round(params["wavelength"] - 0.1, 2))
            need_rebuild = True
        elif ch == ord("W"):
            new_params["wavelength"] = min(3.0, round(params["wavelength"] + 0.1, 2))
            need_rebuild = True
        elif ch == ord("b"):
            new_params["bob"] = max(0.0, round(params["bob"] - 0.1, 2))
            need_rebuild = True
        elif ch == ord("B"):
            new_params["bob"] = min(2.0, round(params["bob"] + 0.1, 2))
            need_rebuild = True
        elif ch == ord("r"):
            new_params = normalize_params(dict(DEFAULT_PARAMS), fallback_id=params["id"])
            need_rebuild = True
        elif ch == ord("e"):
            chosen_id = _prompt_export(stdscr, status_row, cols_term, params["id"])
            if chosen_id:
                new_params["id"] = chosen_id
                try:
                    res = build(source, new_params)
                    out_paths = write_outputs(res.component, res.text, out_dir)
                    status_msg = f"Wrote {', '.join(p.name for p in out_paths)} to {out_dir}"
                    status_is_error = False
                    params = new_params
                    result = res
                except GeneratorError as err:
                    status_msg = f"Export failed: {err}"
                    status_is_error = True
            else:
                status_msg = "Export cancelled."
                status_is_error = False

        if need_rebuild:
            stdscr.move(status_row, 0)
            stdscr.clrtoeol()
            stdscr.addstr(status_row, 0, "converting...")
            stdscr.refresh()
            try:
                new_res = build(source, new_params)
                params = new_params
                result = new_res
                status_msg = "Updated."
                status_is_error = False
            except GeneratorError as exc:
                status_msg = f"Error: {exc}"
                status_is_error = True


def run_tui(path: str, out_dir: str = "out"):
    if not sys.stdin.isatty():
        print("TUI requires an interactive terminal", file=sys.stderr)
        sys.exit(2)
    curses.wrapper(_tui_loop, path, out_dir)
