"""Generate the application icon (.ico + .png) without any external asset.

Run: ``python packaging/make_icons.py``
"""

from __future__ import annotations

import math
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFilter
except ImportError:  # pragma: no cover
    raise SystemExit("Pillow is required: python -m pip install pillow")

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
ASSETS.mkdir(parents=True, exist_ok=True)

ACCENT = (91, 140, 255)
ACCENT_HI = (123, 163, 255)
BACKGROUND_TOP = (24, 32, 60)
BACKGROUND_BOTTOM = (12, 17, 35)
COLOURS = [(91, 140, 255), (55, 211, 153), (255, 180, 84), (255, 97, 136)]


def rounded_gradient(size: int) -> Image.Image:
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    gradient = Image.new("RGBA", (size, size))
    draw = ImageDraw.Draw(gradient)
    for y in range(size):
        ratio = y / max(1, size - 1)
        colour = tuple(
            int(BACKGROUND_TOP[i] + (BACKGROUND_BOTTOM[i] - BACKGROUND_TOP[i]) * ratio)
            for i in range(3)
        )
        draw.line([(0, y), (size, y)], fill=colour + (255,))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, size - 1, size - 1], radius=int(size * 0.22), fill=255)
    image.paste(gradient, (0, 0), mask)
    return image


def draw_mark(image: Image.Image, size: int) -> Image.Image:
    draw = ImageDraw.Draw(image, "RGBA")
    centre = size / 2
    # ripple rings
    for index, radius in enumerate((size * 0.34, size * 0.26)):
        alpha = 70 - index * 20
        width = max(2, int(size * 0.028))
        draw.ellipse(
            [centre - radius, centre - radius, centre + radius, centre + radius],
            outline=ACCENT_HI + (alpha,), width=width,
        )
    # cursor arrow
    tip = (centre - size * 0.02, centre - size * 0.20)
    left = (centre - size * 0.185, centre + size * 0.04)
    right = (centre - size * 0.02, centre + size * 0.055)
    tail = (centre - size * 0.075, centre + size * 0.185)
    draw.polygon([tip, left, right, tail], fill=(255, 255, 255, 245))
    draw.line([tip, left, right, tail], fill=ACCENT + (255,), width=max(1, int(size * 0.012)))
    # click dot
    dot_r = size * 0.115
    glow = Image.new("RGBA", image.size, (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(glow)
    gdraw.ellipse(
        [centre + size * 0.09, centre + size * 0.09, centre + size * 0.09 + dot_r * 2,
         centre + size * 0.09 + dot_r * 2],
        fill=ACCENT + (235,),
    )
    glow = glow.filter(ImageFilter.GaussianBlur(size * 0.012))
    image = Image.alpha_composite(image, glow)
    draw = ImageDraw.Draw(image, "RGBA")
    draw.ellipse(
        [centre + size * 0.11, centre + size * 0.11, centre + size * 0.11 + dot_r * 1.8,
         centre + size * 0.11 + dot_r * 1.8],
        fill=(255, 255, 255, 250),
    )
    return image


def spark_ring(image: Image.Image, size: int) -> Image.Image:
    draw = ImageDraw.Draw(image, "RGBA")
    centre = size / 2
    ring = size * 0.44
    for index in range(24):
        angle = index / 24 * math.tau
        if index % 3:
            continue
        x = centre + math.cos(angle) * ring
        y = centre + math.sin(angle) * ring
        dot = size * 0.012
        draw.ellipse([x - dot, y - dot, x + dot, y + dot], fill=ACCENT_HI + (120,))


def build(size: int = 512) -> Image.Image:
    image = rounded_gradient(size)
    image = draw_mark(image, size)
    spark_ring(image, size)
    return image


def main() -> None:
    master = build(512)
    master.save(ASSETS / "clicks-auto.png")
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    master.save(ASSETS / "clicks-auto.ico", sizes=sizes)
    # A small PNG for docs / release notes.
    build(128).save(ASSETS / "clicks-auto-128.png")
    print(f"Wrote {ASSETS / 'clicks-auto.ico'}")
    print(f"Wrote {ASSETS / 'clicks-auto.png'}")


if __name__ == "__main__":
    main()
