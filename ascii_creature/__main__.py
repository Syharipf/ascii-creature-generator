"""Command-line interface entry point for ascii_creature."""

import argparse
from pathlib import Path
import sys
import traceback

from . import VERSION
from .component import DEFAULT_PARAMS, build, normalize_params
from .errors import GeneratorError
from .export import validate_id, write_outputs
from .image import load_source


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ascii_creature",
        description="Turn creature photos into animated ASCII components.",
    )
    parser.add_argument(
        "-v", "--version", action="version", version=f"ascii-creature-generator {VERSION}"
    )

    subparsers = parser.add_subparsers(dest="command")

    # TUI
    tui_p = subparsers.add_parser("tui", help="Interactive terminal tuning")
    tui_p.add_argument("image", help="Path to input creature image")
    tui_p.add_argument("--out", default="out", help="Output directory (default: out)")

    # GUI
    gui_p = subparsers.add_parser("gui", help="Localhost browser tuning")
    gui_p.add_argument("image", nargs="?", default=None, help="Path to initial image")
    gui_p.add_argument("--out", default="out", help="Output directory (default: out)")
    gui_p.add_argument("--port", type=int, default=0, help="Port to bind (default: 0 = random free port)")
    gui_p.add_argument("--no-browser", action="store_true", help="Do not open browser automatically")

    # Export
    exp_p = subparsers.add_parser("export", help="Batch export component files")
    exp_p.add_argument("image", help="Path to input image")
    exp_p.add_argument("--id", required=True, help="Component slug id (e.g. reef-dragon)")
    exp_p.add_argument("--name", default=None, help="Display name (default: title-cased id)")
    exp_p.add_argument("--out", required=True, help="Output directory")

    exp_p.add_argument("--cols", type=int, default=None, help="Grid columns (8..96)")
    exp_p.add_argument("--tolerance", type=float, default=None, help="Background tolerance (0..160)")
    exp_p.add_argument("--coverage", type=float, default=None, help="Cell coverage threshold (0.05..0.95)")
    exp_p.add_argument("--posterize", type=int, default=None, help="Color quantization levels (0, 2..128)")
    exp_p.add_argument("--head-side", choices=["left", "right"], default=None, help="Head orientation")
    exp_p.add_argument("--preset", choices=["swim", "glide", "flap", "crawl"], default=None, help="Motion preset")
    exp_p.add_argument("--amplitude", type=float, default=None, help="Spine oscillation amplitude")
    exp_p.add_argument("--speed", type=float, default=None, help="Spine oscillation speed")
    exp_p.add_argument("--wavelength", type=float, default=None, help="Spine wavelength")
    exp_p.add_argument("--bob", type=float, default=None, help="Vertical bobbing")
    exp_p.add_argument("--pov", choices=["side", "top", "isometric", "bottom"], default=None, help="Point of view preset")
    exp_p.add_argument("--pitch", type=float, default=None, help="Elevation angle in degrees (-60..60)")
    exp_p.add_argument("--roll", type=float, default=None, help="Dynamic roll factor (0..1)")

    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 0

    try:
        if args.command == "tui":
            from .tui import run_tui
            run_tui(args.image, out_dir=args.out)
            return 0

        elif args.command == "gui":
            from .gui import run_gui
            run_gui(path=args.image, out_dir=args.out, port=args.port, no_browser=args.no_browser)
            return 0

        elif args.command == "export":
            validate_id(args.id)
            source = load_source(args.image)

            raw_params: dict = {
                "id": args.id,
                "name": args.name,
            }
            for key in ["cols", "tolerance", "coverage", "posterize", "amplitude", "speed", "wavelength", "bob", "pitch", "roll"]:
                val = getattr(args, key)
                if val is not None:
                    raw_params[key] = val

            if args.head_side is not None:
                raw_params["head_side"] = args.head_side
            if args.preset is not None:
                raw_params["preset"] = args.preset
            if args.pov is not None:
                raw_params["pov"] = args.pov

            norm = normalize_params(raw_params, fallback_id=args.id)
            result = build(source, norm)
            written = write_outputs(result.component, result.text, args.out)

            for p in written:
                print(str(p.resolve()))
            return 0

    except GeneratorError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except Exception:
        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
