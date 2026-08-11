"""Generate the repository banner (assets/banner.png) and social preview
(assets/social_preview.png) in the project palette. Run: python assets/make_banner.py
"""

from __future__ import annotations

import math

from PIL import Image, ImageDraw, ImageFont

BG = (16, 37, 36)          # 102524
PANEL = (36, 56, 55)       # 243837
LINE = (50, 78, 77)        # 324E4D
INK = (255, 255, 255)
MUTED = (165, 201, 199)    # A5C9C7

PALETTES = {
    "thermal": [(255, 211, 189), (255, 154, 104), (255, 92, 10), (131, 57, 20)],
    "air": [(165, 201, 199), (112, 151, 149), (73, 108, 106), (16, 37, 36)],
    "energy": [(233, 228, 255), (178, 161, 255), (119, 89, 255), (96, 60, 255)],
    "vegetation": [(237, 255, 217), (196, 255, 133), (134, 219, 42), (92, 153, 28)],
}
ACCENTS = {"thermal": (255, 92, 10), "air": (133, 177, 175),
           "energy": (137, 111, 255), "vegetation": (157, 250, 58)}

FONT = "/System/Library/Fonts/Helvetica.ttc"


def colormap(v, stops):
    v = max(0.0, min(1.0, v))
    seg = min(len(stops) - 2, int(v * (len(stops) - 1)))
    t = v * (len(stops) - 1) - seg
    a, b = stops[seg], stops[seg + 1]
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def field(i, j, phase):
    """Smooth synthetic field so the tiles echo the demo heatmaps."""
    return 0.5 + 0.28 * math.sin(i * 0.7 + phase) * math.cos(j * 0.55 + phase * 1.7) \
        + 0.22 * math.sin((i + j) * 0.35 + phase * 2.3)


def draw_tile(draw, x, y, size, cells, palette, phase):
    cell = size / cells
    for j in range(cells):
        for i in range(cells):
            v = field(i, j, phase)
            draw.rectangle([x + i * cell, y + j * cell,
                            x + (i + 1) * cell + 1, y + (j + 1) * cell + 1],
                           fill=colormap(v, palette))


def make(width, height, out, title_px, sub_px, tag_px):
    img = Image.new("RGB", (width, height), BG)
    d = ImageDraw.Draw(img)

    title_f = ImageFont.truetype(FONT, title_px)
    sub_f = ImageFont.truetype(FONT, sub_px)
    tag_f = ImageFont.truetype(FONT, tag_px)

    # Right side: four domain tiles with rounded panel frames.
    tile = int(height * 0.36)
    gap = int(tile * 0.14)
    total = 2 * tile + gap
    x0 = width - total - int(height * 0.22)
    y0 = (height - total) // 2
    for k, (name, palette) in enumerate(PALETTES.items()):
        tx = x0 + (k % 2) * (tile + gap)
        ty = y0 + (k // 2) * (tile + gap)
        d.rounded_rectangle([tx - 6, ty - 6, tx + tile + 6, ty + tile + 6],
                            radius=10, fill=PANEL, outline=LINE, width=2)
        tile_img = Image.new("RGB", (tile, tile), PANEL)
        draw_tile(ImageDraw.Draw(tile_img), 0, 0, tile, 12, palette, phase=k * 1.9)
        mask = Image.new("L", (tile, tile), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, tile, tile], radius=6, fill=255)
        img.paste(tile_img, (tx, ty), mask)
        d.ellipse([tx + tile - 16, ty + 8, tx + tile - 4, ty + 20], fill=ACCENTS[name])

    # Left side: wordmark, subtitle, domain legend.
    lx = int(height * 0.22)
    ly = int(height * 0.26)
    d.text((lx, ly), "UrbanMind", font=title_f, fill=INK)
    ly += title_px + int(sub_px * 0.6)
    d.text((lx, ly), "Urban multi-domain integrated dynamics", font=sub_f, fill=MUTED)
    ly += sub_px + int(sub_px * 0.5)
    d.text((lx, ly), "One shared graph for thermal · air · energy · vegetation",
           font=sub_f, fill=MUTED)

    ly += sub_px + int(sub_px * 1.2)
    for name, color in ACCENTS.items():
        d.ellipse([lx, ly + tag_px * 0.25, lx + tag_px * 0.75, ly + tag_px], fill=color)
        label = {"thermal": "Thermal", "air": "Air quality",
                 "energy": "Building energy", "vegetation": "Vegetation"}[name]
        d.text((lx + tag_px * 1.2, ly), label, font=tag_f, fill=INK)
        lx += tag_px * 1.2 + d.textlength(label, font=tag_f) + tag_px * 1.6

    # Bottom palette strip.
    strip_h = max(6, height // 60)
    seg = width / 4
    for k, color in enumerate(ACCENTS.values()):
        d.rectangle([k * seg, height - strip_h, (k + 1) * seg, height], fill=color)

    img.save(out)
    print("wrote", out, img.size)


if __name__ == "__main__":
    make(1600, 400, "assets/banner.png", title_px=76, sub_px=26, tag_px=20)
    make(1280, 640, "assets/social_preview.png", title_px=96, sub_px=34, tag_px=26)
