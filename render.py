#!/usr/bin/env python3
"""Render pages of a PDF (e.g. a returned, pulled worksheet) for viewing, cheaply.

    python3 render.py file.pdf [--pages 1-3] [--dpi 90] [--sheet] [--crop x0,y0,x1,y1] [-o OUTDIR]

--sheet : all chosen pages side by side in ONE image (one view instead of several)
--crop  : crop box in mm on each page (from top-left), for zooming on a problem row
Prints the output paths. Skip free-notes pages with --pages.
"""
import argparse, os
import pymupdf
from PIL import Image

ap = argparse.ArgumentParser()
ap.add_argument("pdf"); ap.add_argument("--pages"); ap.add_argument("--dpi", type=int, default=90)
ap.add_argument("--sheet", action="store_true"); ap.add_argument("--crop"); ap.add_argument("-o", "--outdir", default="out")
a = ap.parse_args()
d = pymupdf.open(a.pdf)
if a.pages:
    lo, _, hi = a.pages.partition("-")
    idx = list(range(int(lo) - 1, int(hi or lo)))
else:
    idx = list(range(len(d)))
os.makedirs(a.outdir, exist_ok=True)
stem = os.path.splitext(os.path.basename(a.pdf))[0]
ims, paths = [], []
for i in idx:
    p = d[i]
    clip = None
    if a.crop:
        x0, y0, x1, y1 = [float(v) * 72 / 25.4 for v in a.crop.split(",")]
        clip = pymupdf.Rect(x0, y0, x1, y1)
    pm = p.get_pixmap(dpi=a.dpi, clip=clip)
    im = Image.frombytes("RGB", (pm.width, pm.height), pm.samples)
    ims.append(im)
    path = os.path.join(a.outdir, f"{stem}_p{i + 1}.png")
    if not a.sheet:
        im.save(path); paths.append(path)
if a.sheet:
    sheet = Image.new("RGB", (sum(i.width for i in ims) + 8 * (len(ims) - 1), max(i.height for i in ims)), "white")
    x = 0
    for im in ims:
        sheet.paste(im, (x, 0)); x += im.width + 8
    path = os.path.join(a.outdir, f"{stem}_sheet.png"); sheet.save(path); paths = [path]
print("\n".join(paths))
