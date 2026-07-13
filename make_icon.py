"""Generates icon.icns (app icon) and menubar_icon.png (status bar glyph).

Run with: uv run python make_icon.py
Requires the macOS `iconutil` CLI (ships with Xcode command line tools).
"""
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw

BG = (30, 33, 40, 255)        # panel dark
ACCENT = (110, 168, 254, 255)  # accent blue
WHITE = (255, 255, 255, 255)

HERE = Path(__file__).parent
ICONSET = HERE / "icon.iconset"


def draw_app_icon(size):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    radius = round(size * 0.22)
    draw.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=BG)

    margin = round(size * 0.156)
    draw.rounded_rectangle(
        [margin, margin, size - margin, size - margin],
        radius=round(size * 0.11),
        outline=ACCENT,
        width=max(2, round(size * 0.039)),
    )

    box = round(size * 0.219)
    bx, by = round(size * 0.289), round(size * 0.375)
    draw.rounded_rectangle(
        [bx, by, bx + box, by + box],
        radius=round(size * 0.047),
        fill=ACCENT,
    )
    w = max(2, round(size * 0.031))
    draw.line(
        [
            (bx + round(box * 0.23), by + round(box * 0.54)),
            (bx + round(box * 0.43), by + round(box * 0.75)),
            (bx + round(box * 0.80), by + round(box * 0.27)),
        ],
        fill=WHITE,
        width=w,
        joint="curve",
    )

    line_x0 = round(size * 0.586)
    h = max(2, round(size * 0.047))
    for i, frac in enumerate([0.391, 0.5, 0.609]):
        y = round(size * frac)
        lw = round(size * (0.18 if i != 1 else 0.133))
        draw.rounded_rectangle(
            [line_x0, y, line_x0 + lw, y + h],
            radius=h // 2,
            fill=(200, 205, 215, 255),
        )
    return img


def draw_menubar_glyph(size):
    """Simple checkbox glyph for the menu bar status item (no panel bg)."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    margin = round(size * 0.12)
    draw.rounded_rectangle(
        [margin, margin, size - margin, size - margin],
        radius=round(size * 0.22),
        fill=ACCENT,
    )
    w = max(2, round(size * 0.09))
    draw.line(
        [
            (size * 0.30, size * 0.52),
            (size * 0.44, size * 0.68),
            (size * 0.72, size * 0.32),
        ],
        fill=WHITE,
        width=w,
        joint="curve",
    )
    return img


def build_icns():
    if ICONSET.exists():
        shutil.rmtree(ICONSET)
    ICONSET.mkdir()

    specs = [
        ("icon_16x16.png", 16),
        ("icon_16x16@2x.png", 32),
        ("icon_32x32.png", 32),
        ("icon_32x32@2x.png", 64),
        ("icon_128x128.png", 128),
        ("icon_128x128@2x.png", 256),
        ("icon_256x256.png", 256),
        ("icon_256x256@2x.png", 512),
        ("icon_512x512.png", 512),
        ("icon_512x512@2x.png", 1024),
    ]
    for name, px in specs:
        draw_app_icon(px).save(ICONSET / name)

    subprocess.run(
        ["iconutil", "-c", "icns", str(ICONSET), "-o", str(HERE / "icon.icns")],
        check=True,
    )
    shutil.rmtree(ICONSET)
    print("saved icon.icns")


def build_menubar_png():
    draw_menubar_glyph(44).save(HERE / "menubar_icon.png")
    print("saved menubar_icon.png")


if __name__ == "__main__":
    build_icns()
    build_menubar_png()
