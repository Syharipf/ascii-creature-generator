"""Image ingest, background masking, and cropping."""

from dataclasses import dataclass, field
from pathlib import Path
import numpy as np
from PIL import Image, ImageOps

from .errors import GeneratorError

MAX_WORK_SIDE = 640
MAX_SOURCE_PIXELS = 40_000_000
ALPHA_THRESHOLD = 128


@dataclass
class Source:
    path: str
    name: str
    orig_size: tuple[int, int]
    work_size: tuple[int, int]
    rgb: np.ndarray
    alpha: np.ndarray | None
    bg_mode: str
    bg_color: str | None
    mask_cache: dict[str, np.ndarray] = field(default_factory=dict)


def load_source(path: str | Path) -> Source:
    path_obj = Path(path)
    try:
        img = Image.open(path_obj)
        img = ImageOps.exif_transpose(img)
    except Exception as exc:
        raise GeneratorError(f"Cannot read image: {path_obj.name}") from exc

    w, h = img.size
    if w * h > MAX_SOURCE_PIXELS:
        raise GeneratorError("Image too large (max 40,000,000 pixels)")

    orig_size = (w, h)
    img = img.convert("RGBA")
    max_dim = max(w, h)
    if max_dim > MAX_WORK_SIDE:
        scale = MAX_WORK_SIDE / max_dim
        new_w = max(1, round(w * scale))
        new_h = max(1, round(h * scale))
        img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

    work_size = img.size
    arr = np.array(img, dtype=np.uint8)
    rgb = arr[:, :, :3]
    alpha = arr[:, :, 3]

    has_alpha = bool((alpha < 250).any())
    if has_alpha:
        bg_mode = "alpha"
        bg_color = None
        stored_alpha = alpha
    else:
        bg_mode = "color"
        stored_alpha = None
        top = rgb[0, :, :]
        bottom = rgb[-1, :, :]
        left = rgb[1:-1, 0, :] if rgb.shape[0] > 2 else rgb[0:0, 0, :]
        right = rgb[1:-1, -1, :] if rgb.shape[0] > 2 else rgb[0:0, 0, :]
        border = np.concatenate([top, bottom, left, right], axis=0)
        med = np.median(border, axis=0).astype(int)
        bg_color = f"#{int(med[0]):02x}{int(med[1]):02x}{int(med[2]):02x}"

    return Source(
        path=str(path_obj.resolve()),
        name=path_obj.name,
        orig_size=orig_size,
        work_size=work_size,
        rgb=rgb,
        alpha=stored_alpha,
        bg_mode=bg_mode,
        bg_color=bg_color,
    )


def _flood_fill_bg(cand: np.ndarray) -> np.ndarray:
    h, w = cand.shape
    cand_flat = cand.ravel()
    visited = bytearray(h * w)
    stack: list[int] = []

    # Top & bottom borders
    for x in range(w):
        if cand_flat[x]:
            visited[x] = 1
            stack.append(x)
        bot = (h - 1) * w + x
        if cand_flat[bot] and not visited[bot]:
            visited[bot] = 1
            stack.append(bot)

    # Left & right borders
    for y in range(1, h - 1):
        left_idx = y * w
        if cand_flat[left_idx] and not visited[left_idx]:
            visited[left_idx] = 1
            stack.append(left_idx)
        right_idx = y * w + (w - 1)
        if cand_flat[right_idx] and not visited[right_idx]:
            visited[right_idx] = 1
            stack.append(right_idx)

    while stack:
        idx = stack.pop()
        y = idx // w
        x = idx % w

        if y > 0:
            up = idx - w
            if cand_flat[up] and not visited[up]:
                visited[up] = 1
                stack.append(up)
        if y < h - 1:
            down = idx + w
            if cand_flat[down] and not visited[down]:
                visited[down] = 1
                stack.append(down)
        if x > 0:
            left = idx - 1
            if cand_flat[left] and not visited[left]:
                visited[left] = 1
                stack.append(left)
        if x < w - 1:
            right = idx + 1
            if cand_flat[right] and not visited[right]:
                visited[right] = 1
                stack.append(right)

    bg_arr = np.frombuffer(visited, dtype=np.uint8).reshape((h, w))
    return bg_arr != 0


def build_mask(source: Source, tolerance: float) -> np.ndarray:
    if source.bg_mode == "alpha":
        cache_key = "alpha"
        if cache_key in source.mask_cache:
            return source.mask_cache[cache_key]
        assert source.alpha is not None
        mask = source.alpha >= ALPHA_THRESHOLD
    else:
        cache_key = f"{tolerance:.2f}"
        if cache_key in source.mask_cache:
            return source.mask_cache[cache_key]
        assert source.bg_color is not None
        hex_c = source.bg_color.lstrip("#")
        bg_rgb = np.array([int(hex_c[0:2], 16), int(hex_c[2:4], 16), int(hex_c[4:6], 16)], dtype=np.int32)
        diff = source.rgb.astype(np.int32) - bg_rgb
        dist_sq = np.sum(diff * diff, axis=2)
        tol_sq = float(tolerance) ** 2
        cand = dist_sq <= tol_sq
        bg_visited = _flood_fill_bg(cand)
        mask = ~bg_visited

    if not mask.any():
        raise GeneratorError("No foreground found after background removal; lower the tolerance or use a transparent PNG.")

    source.mask_cache[cache_key] = mask
    return mask


def crop_to_mask(rgb: np.ndarray, mask: np.ndarray) -> tuple[np.ndarray, np.ndarray, tuple[int, int, int, int]]:
    ys, xs = np.where(mask)
    if len(ys) == 0:
        raise GeneratorError("No foreground found after background removal; lower the tolerance or use a transparent PNG.")
    y0, y1 = int(ys.min()), int(ys.max() + 1)
    x0, x1 = int(xs.min()), int(xs.max() + 1)
    return rgb[y0:y1, x0:x1], mask[y0:y1, x0:x1], (x0, y0, x1, y1)
