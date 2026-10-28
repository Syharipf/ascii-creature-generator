"""Generate synthetic image fixtures for testing."""

from pathlib import Path
import sys
from PIL import Image, ImageDraw


def _draw_creature_shapes(draw: ImageDraw.ImageDraw):
    # Body ellipse
    draw.ellipse((96, 120, 360, 300), fill="#d67830")
    # Tail polygon
    draw.polygon([(360, 180), (470, 120), (470, 270), (360, 240)], fill="#d67830")
    # Fin polygon
    draw.polygon([(210, 220), (300, 300), (320, 220)], fill="#f0c878")
    # Eye ellipse
    draw.ellipse((150, 160, 190, 200), fill="#141820")


def make_fixtures(out_dir: str | Path) -> dict[str, Path]:
    dir_path = Path(out_dir).resolve()
    dir_path.mkdir(parents=True, exist_ok=True)

    # 1. fish.png
    fish_img = Image.new("RGB", (512, 384), "#2f6f8f")
    _draw_creature_shapes(ImageDraw.Draw(fish_img))
    fish_path = dir_path / "fish.png"
    fish_img.save(fish_path)

    # 2. cutout.png
    cutout_img = Image.new("RGBA", (512, 384), (0, 0, 0, 0))
    _draw_creature_shapes(ImageDraw.Draw(cutout_img))
    cutout_path = dir_path / "cutout.png"
    cutout_img.save(cutout_path)

    # 3. empty.png
    empty_img = Image.new("RGB", (512, 384), "#2f6f8f")
    empty_path = dir_path / "empty.png"
    empty_img.save(empty_path)

    return {
        "fish": fish_path,
        "cutout": cutout_path,
        "empty": empty_path,
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 checks/fixture.py OUT_DIR", file=sys.stderr)
        sys.exit(1)
    paths = make_fixtures(sys.argv[1])
    for p in paths.values():
        print(str(p))
