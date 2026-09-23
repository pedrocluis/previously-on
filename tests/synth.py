"""Render synthetic 1920x1080 frames that mimic Elden Ring HUD text.

Not a substitute for real screenshots, but enough to exercise the full
OCR → classify path without the game installed.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from previously_on.regions import Region

W, H = 1920, 1080

_FONT_CANDIDATES = [
    "/usr/share/fonts/gnu-free/FreeSerif.otf",
    "/usr/share/fonts/liberation/LiberationSerif-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
    "/usr/share/fonts/TTF/DejaVuSerif.ttf",
    "C:/Windows/Fonts/georgia.ttf",
    "C:/Windows/Fonts/times.ttf",
]

GOLD = (214, 181, 106)
RED = (150, 30, 30)
WHITE = (235, 235, 235)


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in _FONT_CANDIDATES:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size=size)


def background(seed: int = 0) -> Image.Image:
    """Dark, slightly noisy backdrop so text is not on a perfectly flat field."""
    rng = np.random.default_rng(seed)
    base = rng.integers(20, 60, size=(H // 8, W // 8, 3), dtype=np.uint8)
    img = Image.fromarray(base).resize((W, H), Image.BILINEAR)
    return img


def draw_text_in_region(
    img: Image.Image, region: Region, text: str, color: tuple[int, int, int], size: int, align: str = "center"
) -> None:
    draw = ImageDraw.Draw(img)
    font = _font(size)
    x0, y0, x1, y1 = region.pixel_box(W, H)
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    cy = (y0 + y1) // 2 - th // 2 - bbox[1]
    if align == "center":
        cx = (x0 + x1) // 2 - tw // 2
    elif align == "item":
        # Elden Ring's pickup row: the name is right-aligned at ~70% of the box, count to its right.
        cx = x0 + int((x1 - x0) * 0.7) - tw
    else:
        cx = x0 + 24
    # Faint shadow, as the game's banners have.
    draw.text((cx + 2, cy + 2), text, font=font, fill=(0, 0, 0))
    draw.text((cx, cy), text, font=font, fill=color)


def to_bgr(img: Image.Image) -> np.ndarray:
    return np.asarray(img.convert("RGB"))[:, :, ::-1].copy()


def frame_with(region: Region, text: str, color=GOLD, size: int = 72, seed: int = 0, align: str = "center") -> np.ndarray:
    img = background(seed)
    draw_text_in_region(img, region, text, color, size, align=align)
    if region.name == "boss_bar":
        draw_boss_hp_bar(img)
    return to_bgr(img)


def blank_frame(seed: int = 0) -> np.ndarray:
    return to_bgr(background(seed))


def draw_boss_hp_bar(img: Image.Image) -> None:
    """The boss HP bar under the name: dark band with a light border line, x 0.24-0.76."""
    draw = ImageDraw.Draw(img)
    x0, x1 = int(0.24 * W), int(0.76 * W)
    y = int(0.805 * H)
    draw.rectangle([x0, y - 4, x1, y + 4], fill=(25, 20, 20))
    draw.line([(x0, y + 4), (x1, y + 4)], fill=(170, 165, 150), width=2)
