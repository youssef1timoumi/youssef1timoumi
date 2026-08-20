#!/usr/bin/env python3
"""Turn avatar.jpg into ascii.svg -- an animated typing portrait.

The portrait is one <text> element per row of characters, revealed left to
right by a clipPath with a cursor block riding the edge. Motion is SMIL rather
than script because GitHub strips <script> from README images.

Two things earn their keep in the pipeline:

  * the sharpening happens after the image is resampled to three times the
    character grid, not at photo resolution. Detail sharpened at 1148px is
    averaged away by a 10x downsample; at grid scale it survives, which is the
    difference between a face with eyes and a bright blob.
  * the tone curve spreads the skin's narrow 180-255 band across most of the
    ramp. Straight brightness clips every skin pixel to the densest glyph.

The JetBrains Mono subset is inlined as a data URI: these SVGs load through
<img>, and browsers refuse to fetch subresources for an image document, so an
external font URL would silently fall back and squeeze the character grid.

    python scripts/generate_ascii.py            # write ascii.svg
    python scripts/generate_ascii.py --preview  # print the art as text
"""
import base64
import os
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageOps

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONT = os.path.join(ROOT, "scripts", "fonts", "jbmono-ramp.woff2")
SRC = os.path.join(ROOT, "avatar.jpg")
OUT = os.path.join(ROOT, "ascii.svg")

# Light to dark. The stat graphics quote steps of this same ramp, so the whole
# header reads as one material.
RAMP = " .`:-=+*cs#%@"
COLS = 114                       # characters per row
CELL_W, CELL_H = 7.74, 15.0      # 0.600em advance at 12.9px, and the line box
PAD_X, PAD_Y = 14, 15
SHARPEN = 260                    # unsharp percentage, applied at grid scale
GAMMA = 1.25
# Input level -> output level. Lifts the hair away from black and gives the
# skin room to shade instead of clipping.
CURVE = [(0, 0), (80, 15), (140, 50), (180, 105), (212, 185), (238, 240),
         (255, 255)]
ROW_DUR = 0.09                   # seconds per row of typing

LIGHT, DARK = "#6e7681", "#c9d1d9"


def lut(points):
    table = []
    for v in range(256):
        for (x0, y0), (x1, y1) in zip(points, points[1:]):
            if x0 <= v <= x1:
                t = (v - x0) / (x1 - x0) if x1 > x0 else 0.0
                table.append(int(y0 + t * (y1 - y0)))
                break
        else:
            table.append(points[-1][1])
    return table


def to_rows(path, cols=COLS):
    img = Image.open(path).convert("L")
    w, h = img.size
    side = min(w, h)
    img = img.crop(((w - side) // 2, (h - side) // 2,
                    (w + side) // 2, (h + side) // 2))
    img = ImageOps.autocontrast(img, cutoff=1)

    # Fade the frame's edge into the page so the head floats instead of
    # ending on a hard square.
    mask = Image.new("L", (side, side), 0)
    ImageDraw.Draw(mask).ellipse(
        (side * 0.03, -side * 0.03, side * 0.97, side * 1.08), fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(radius=side * 0.06))
    img = Image.composite(img, Image.new("L", (side, side), 0), mask)

    rows = round(cols * (CELL_W / CELL_H))      # keep the square square
    img = img.resize((cols * 3, rows * 3), Image.Resampling.LANCZOS)
    img = img.filter(ImageFilter.UnsharpMask(radius=3, percent=SHARPEN,
                                             threshold=1))
    img = img.resize((cols, rows), Image.Resampling.LANCZOS).point(lut(CURVE))

    px = img.tobytes()
    out = []
    for r in range(rows):
        line = ""
        for v in px[r * cols:(r + 1) * cols]:
            i = int(((v / 255.0) ** GAMMA) * (len(RAMP) - 1) + 0.5)
            line += RAMP[min(len(RAMP) - 1, max(0, i))]
        out.append(line.rstrip())
    while out and not out[0].strip():
        out.pop(0)
    while out and not out[-1].strip():
        out.pop()
    return out


def font_face():
    with open(FONT, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    return ("@font-face{font-family:JBMono;font-style:normal;font-weight:400;"
            f"font-display:block;src:url(data:font/woff2;base64,{b64}) "
            "format('woff2')}")


def to_svg(rows):
    width = int(max(len(r) for r in rows) * CELL_W + PAD_X * 2)
    height = int(len(rows) * CELL_H + PAD_Y * 2)
    mono = ("JBMono,ui-monospace,SFMono-Regular,Menlo,Consolas,"
            "&apos;Liberation Mono&apos;,monospace")

    p = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
         f'height="{height}" viewBox="0 0 {width} {height}" '
         f'font-family="{mono}">',
         f'<style>{font_face()}.a{{fill:{LIGHT}}}'
         f'@media(prefers-color-scheme:dark){{.a{{fill:{DARK}}}}}</style>']

    for i, row in enumerate(rows):
        text = (row.replace("&", "&amp;").replace("<", "&lt;")
                   .replace(">", "&gt;"))
        y_box = PAD_Y + i * CELL_H
        begin = i * ROW_DUR
        w = len(row) * CELL_W
        p.append(f'<clipPath id="r{i}"><rect x="{PAD_X}" y="{y_box - 1:.1f}" '
                 f'height="{CELL_H}" width="0"><animate attributeName="width" '
                 f'from="0" to="{w:.1f}" begin="{begin:.2f}s" '
                 f'dur="{ROW_DUR}s" fill="freeze"/></rect></clipPath>')
        p.append(f'<g clip-path="url(#r{i})"><text xml:space="preserve" '
                 f'x="{PAD_X}" y="{y_box + 11.2:.1f}" class="a" '
                 f'font-size="12.9">{text}</text></g>')
        p.append(f'<rect y="{y_box:.1f}" width="5" height="12" class="a" '
                 f'opacity="0"><animate attributeName="x" from="{PAD_X}" '
                 f'to="{PAD_X + w:.1f}" begin="{begin:.2f}s" dur="{ROW_DUR}s" '
                 f'fill="freeze"/><set attributeName="opacity" to="0.8" '
                 f'begin="{begin:.2f}s"/><set attributeName="opacity" to="0" '
                 f'begin="{begin + ROW_DUR:.2f}s"/></rect>')

    p.append("</svg>")
    return "".join(p)


def main():
    rows = to_rows(SRC)
    if "--preview" in sys.argv:
        print("\n".join(rows))
        return
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(to_svg(rows))
    print(f"ascii.svg: {len(rows)} rows x {max(len(r) for r in rows)} cols")


if __name__ == "__main__":
    main()
