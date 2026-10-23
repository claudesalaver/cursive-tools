#!/usr/bin/env python3
"""
Cursive worksheet generator — black & white only, sized for the reMarkable 2 by default.

Usage:
    python3 make_worksheet.py session.json [-o out.pdf]

Session JSON format: context/worksheet_spec.md.
Dependencies: reportlab, fontTools, uharfbuzz  (pip install --break-system-packages uharfbuzz)
Fonts are downloaded from the google/fonts GitHub repo on first run (SIL OFL).

Why HarfBuzz: Playwrite fonts build their letter joins with OpenType contextual
alternates (calt). Plain reportlab text drops them and the joins break. Text is
shaped with HarfBuzz and drawn as glyph outlines, which also allows hollow and
dotted "trace" letters and an optional extra slant.

Colour rule: everything is pure black (no gray) — the reMarkable 2 is a
monochrome e-ink display. Fade levels are distinguished by line style
(solid fill -> solid outline -> dotted outline -> nothing), not by gray.
"""
import argparse, json, math, os, sys, urllib.request, datetime, shutil

from fontTools.ttLib import TTFont
from fontTools.pens.basePen import BasePen
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.boundsPen import BoundsPen
import uharfbuzz as hb
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter, A4
from reportlab.lib.units import mm

HERE = os.path.dirname(os.path.abspath(__file__))
FONT_DIR = os.environ.get("CURSIVE_FONT_DIR", os.path.join(HERE, "..", "fonts"))
RAW = "https://raw.githubusercontent.com/google/fonts/main/"

# reMarkable 2 screen: 1404 x 1872 px at 226 dpi = 157.8 x 210.4 mm. A PDF this size shows 1:1
# (a Letter page would be shrunk to ~73%, so a 5 mm x-height would appear as ~3.7 mm).
RM2 = (1404 / 226 * 72, 1872 / 226 * 72)
PAGES = {"rm2": RM2, "letter": letter, "a4": A4}

# key: (file stem, repo path, is_variable, label, inherent slant in deg from vertical [estimated])
FONTS = {
    "trad":   ("PlaywriteUSTrad",   "ofl/playwriteustrad/PlaywriteUSTrad%5Bwght%5D.ttf",     True,
               "Playwrite US Trad (traditional US school cursive)", 14),
    "modern": ("PlaywriteUSModern", "ofl/playwriteusmodern/PlaywriteUSModern%5Bwght%5D.ttf", True,
               "Playwrite US Modern (D'Nealian-style, mostly unjoined)", 10),
    "formal": ("PinyonScript",      "ofl/pinyonscript/PinyonScript-Regular.ttf",            False,
               "Pinyon Script (copperplate/Spencerian-like display font)", 35),
    "casual": ("DancingScript",     "ofl/dancingscript/DancingScript%5Bwght%5D.ttf",       True,
               "Dancing Script (modern casual script)", 15),
}

# all black; (line width pt, dash pattern or None)
GUIDE = {
    "base":  (0.75, None),          # baseline: strongest line
    "mid":   (0.45, (2.0, 1.6)),    # x-height midline: dashed
    "outer": (0.35, None),          # ascender / descender lines: thin solid
    "slant": (0.3, (0.6, 2.6)),     # slant guides: sparse dots
}
# trace / faint letters are drawn as dots along the letter's centre line (skeleton of the glyph):
# (dot spacing mm, dot radius mm). Outline mode ("outline" style) is kept as an option.
TRACE_DOTS = (0.75, 0.24)
FAINT_DOTS = (1.6, 0.17)
OUTLINE_W = 0.5


# ----------------------------------------------------------------- fonts ---

def ensure_font(key):
    stem, path, variable, _, _ = FONTS[key]
    os.makedirs(FONT_DIR, exist_ok=True)
    static = os.path.join(FONT_DIR, stem + "-static.ttf")
    if os.path.exists(static):
        return static
    raw = os.path.join(FONT_DIR, stem + ".ttf")
    if not os.path.exists(raw):
        urllib.request.urlretrieve(RAW + path, raw)
    if variable:
        from fontTools.varLib import instancer
        f = TTFont(raw)
        loc = {}
        for a in f["fvar"].axes:
            loc[a.axisTag] = 400 if (a.axisTag == "wght" and a.minValue <= 400 <= a.maxValue) else a.defaultValue
        instancer.instantiateVariableFont(f, loc).save(static)
    else:
        shutil.copy(raw, static)
    return static


class _RLPen(BasePen):
    """fontTools pen -> reportlab path."""
    def __init__(self, glyphset, path):
        super().__init__(glyphset); self.p = path
    def _moveTo(self, pt): self.p.moveTo(*pt)
    def _lineTo(self, pt): self.p.lineTo(*pt)
    def _curveToOne(self, a, b, c): self.p.curveTo(a[0], a[1], b[0], b[1], c[0], c[1])
    def _closePath(self): self.p.close()


class _FlatPen(BasePen):
    """Collects contours as flattened polylines (curves sampled)."""
    def __init__(self, glyphset, steps=12):
        super().__init__(glyphset); self.contours = []; self.cur = []; self.steps = steps
    def _moveTo(self, pt): self.cur = [pt]
    def _lineTo(self, pt): self.cur.append(pt)
    def _curveToOne(self, a, b, c):
        p0 = self.cur[-1]
        for i in range(1, self.steps + 1):
            t = i / self.steps; mt = 1 - t
            self.cur.append((mt**3*p0[0] + 3*mt*mt*t*a[0] + 3*mt*t*t*b[0] + t**3*c[0],
                             mt**3*p0[1] + 3*mt*mt*t*a[1] + 3*mt*t*t*b[1] + t**3*c[1]))
    def _closePath(self):
        if len(self.cur) > 2: self.contours.append(self.cur)
        self.cur = []
    _endPath = _closePath


class CursiveFont:
    def __init__(self, key):
        self.key = key
        self.path = ensure_font(key)
        self.tt = TTFont(self.path)
        self.gs = self.tt.getGlyphSet()
        self.order = self.tt.getGlyphOrder()
        self.upem = self.tt["head"].unitsPerEm
        self.label = FONTS[key][3]
        self.name = self.label.split(" (")[0]
        self.slant = FONTS[key][4]
        self.hbfont = hb.Font(hb.Face(hb.Blob.from_file_path(self.path)))
        cmap = self.tt.getBestCmap()

        def bnd(chars, i):
            vals = []
            for ch in chars:
                g = cmap.get(ord(ch))
                if g:
                    bp = BoundsPen(self.gs); self.gs[g].draw(bp)
                    if bp.bounds: vals.append(bp.bounds[i])
            return vals
        self.xh = sum(bnd("xvwz", 3)) / 4                # x-height (font units)
        self.asc = max(bnd("bdhklt", 3))                 # loop tops
        self.cap = max(bnd("HKLTE", 3) or [self.asc])
        self.desc = min(bnd("gjpqyz", 1))                # descender (negative)

    def shape(self, text):
        buf = hb.Buffer(); buf.add_str(text); buf.guess_segment_properties()
        hb.shape(self.hbfont, buf, {"kern": True, "liga": True, "calt": True})
        out, x = [], 0
        for info, pos in zip(buf.glyph_infos, buf.glyph_positions):
            out.append((self.order[info.codepoint], x + pos.x_offset, pos.y_offset))
            x += pos.x_advance
        return out, x

    def width(self, text, scale):
        return self.shape(text)[1] * scale

    def centerline_dots(self, text, scale, skew_deg, spacing):
        """Points (pt, relative to the baseline origin) spaced ~`spacing` pt along the glyphs' centre lines."""
        key = (text, round(scale, 6), skew_deg, round(spacing, 3))
        if key in getattr(self, "_cache", {}):
            return self._cache[key]
        import numpy as np
        from PIL import Image, ImageDraw
        from skimage.morphology import skeletonize
        R = 10.0                                             # raster px per pt
        sk = math.tan(math.radians(skew_deg))
        glyphs, _ = self.shape(text)
        polys = []                                           # per glyph: list of contours in pt
        for name, gx, gy in glyphs:
            fp = _FlatPen(self.gs)
            self.gs[name].draw(TransformPen(fp, (scale, 0, scale * sk, scale, gx * scale, gy * scale)))
            if fp.contours: polys.append(fp.contours)
        if not polys:
            return []
        xs = [p[0] for g in polys for cn in g for p in cn]; ys = [p[1] for g in polys for cn in g for p in cn]
        x0, y0 = min(xs) - 2, min(ys) - 2
        W, H = int((max(xs) - x0 + 2) * R), int((max(ys) - y0 + 2) * R)
        acc = np.zeros((H, W), bool)
        for g in polys:
            wind = np.zeros((H, W), np.int16)   # nonzero winding rule (TrueType; contours may overlap)
            for cn in g:
                area = sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(cn, cn[1:] + cn[:1]))
                im = Image.new("1", (W, H), 0)
                ImageDraw.Draw(im).polygon([((px - x0) * R, H - (py - y0) * R) for px, py in cn], fill=1)
                wind += np.array(im, np.int16) * (1 if area > 0 else -1)
            acc |= wind != 0
        skel = skeletonize(acc)
        yy, xx = np.nonzero(skel)
        pts = sorted(zip(xx.tolist(), yy.tolist()))
        d = spacing * R; cell = {}; out = []
        for px, py in pts:
            ci, cj = int(px // d), int(py // d)
            ok = True
            for di in (-1, 0, 1):
                for dj in (-1, 0, 1):
                    for qx, qy in cell.get((ci + di, cj + dj), ()):
                        if (qx - px) ** 2 + (qy - py) ** 2 < d * d:
                            ok = False; break
                    if not ok: break
                if not ok: break
            if ok:
                cell.setdefault((ci, cj), []).append((px, py)); out.append((px / R + x0, (H - py) / R + y0))
        self.__dict__.setdefault("_cache", {})[key] = out
        return out

    def draw(self, c, text, x, y, scale, style="model", skew_deg=0.0):
        if style == "blank" or not text:
            return
        if style in ("trace", "faint"):
            sp, r = TRACE_DOTS if style == "trace" else FAINT_DOTS
            c.saveState(); c.setFillColorRGB(0, 0, 0)
            for px, py in self.centerline_dots(text, scale, skew_deg, sp * mm):
                c.circle(x + px, y + py, r * mm, stroke=0, fill=1)
            c.restoreState()
            return
        glyphs, _ = self.shape(text)
        sk = math.tan(math.radians(skew_deg))
        path = c.beginPath()
        pen = _RLPen(self.gs, path)
        for name, gx, gy in glyphs:
            # shear around the baseline: x' = x + s*(gx + u + sk*v), y' = y + s*(gy + v)
            t = TransformPen(pen, (scale, 0, scale * sk, scale, x + gx * scale, y + gy * scale))
            self.gs[name].draw(t)
        c.saveState()
        c.setStrokeColorRGB(0, 0, 0); c.setFillColorRGB(0, 0, 0)
        c.setLineJoin(1); c.setLineCap(1)
        if style == "model":
            c.drawPath(path, stroke=0, fill=1, fillMode=1)  # reportlab: 1 = nonzero winding
        else:  # outline
            c.setLineWidth(OUTLINE_W); c.drawPath(path, stroke=1, fill=0)
        c.restoreState()


# ------------------------------------------------------------- worksheet ---

class Sheet:
    def __init__(self, spec, out):
        self.spec = spec
        self.font = CursiveFont(spec.get("font", "trad"))
        self.pagesize = PAGES[spec.get("page", "rm2").lower()]
        self.W, self.H = self.pagesize
        small = self.pagesize == RM2
        self.ml = self.mr = spec.get("margin_mm", 8 if small else 13) * mm
        self.mt = spec.get("margin_top_mm", 13 if small else 13) * mm   # rM2: clear the toolbar toggle
        self.mb = spec.get("margin_bottom_mm", 9 if small else 13) * mm
        self.xh_mm = spec.get("xheight_mm", 5)
        self.scale = self.xh_mm * mm / self.font.xh
        self.skew = spec.get("extra_slant_deg", 0)
        self.slant = spec.get("slant_guide_deg", self.font.slant + self.skew)  # from vertical
        self.c = canvas.Canvas(out, pagesize=self.pagesize)
        self.c.setTitle(f"Cursive {spec.get('session', '')} - {spec.get('focus', '')}")
        self.c.setFillColorRGB(0, 0, 0); self.c.setStrokeColorRGB(0, 0, 0)
        self.pages = 1
        self.y = self.H - self.mt
        self.header(first=True)

    @property
    def tw(self): return self.W - self.ml - self.mr
    @property
    def above(self): return self.font.asc * self.scale * 1.04
    @property
    def below(self): return -self.font.desc * self.scale * 1.04
    @property
    def row_h(self): return self.above + self.below + self.spec.get("row_gap_mm", 1.5) * mm

    def ensure(self, h):
        if self.y - h < self.mb + 6 * mm:
            self.footer(); self.c.showPage(); self.pages += 1
            self.y = self.H - self.mt; self.header(first=False)

    def _wrap(self, text, font, size, width):
        lines = []
        for para in str(text).split("\n"):
            line = ""
            for w in para.split():
                t = (line + " " + w).strip()
                if self.c.stringWidth(t, font, size) > width and line:
                    lines.append(line); line = w
                else:
                    line = t
            lines.append(line)
        return lines

    def header(self, first):
        c, s = self.c, self.spec
        if first:
            title = f"Session {s.get('session', '?')} — {s.get('focus', '')}"
            for ln in self._wrap(title, "Helvetica-Bold", 11, self.tw):
                c.setFont("Helvetica-Bold", 11); c.drawString(self.ml, self.y - 10, ln); self.y -= 13
            d = s.get("date") or datetime.date.today().isoformat()
            c.setFont("Helvetica", 7.5)
            c.drawString(self.ml, self.y - 8, f"{d} · {s.get('stage', '')} · x-height {self.xh_mm} mm · model: {self.font.name}")
            c.drawString(self.ml, self.y - 18, "Start ____:____   End ____:____   Effort 1 2 3 4 5   Hardest: ____________")
            # grip box: tick one
            gx = self.ml
            c.drawString(gx, self.y - 28, "Grip:"); gx += c.stringWidth("Grip:", "Helvetica", 7.5) + 5
            for lab in ("tight", "middle", "loose"):
                c.setLineWidth(0.6); c.rect(gx, self.y - 29, 6.5, 6.5, stroke=1, fill=0)
                c.drawString(gx + 9, self.y - 28, lab); gx += 9 + c.stringWidth(lab, "Helvetica", 7.5) + 10
            c.drawString(gx + 6, self.y - 28, "Pressure felt: light / medium / heavy")
            c.setLineWidth(0.6); c.line(self.ml, self.y - 33, self.W - self.mr, self.y - 33)
            self.y -= 39
        else:
            c.setFont("Helvetica", 7.5)
            c.drawString(self.ml, self.y - 8, f"Session {s.get('session', '?')} (cont.)")
            self.y -= 13

    def footer(self):
        c = self.c
        c.setFont("Helvetica", 5.5)
        c.drawString(self.ml, self.mb - 4,
                     f"p.{self.pages} · Model letters: {self.font.name} (SIL Open Font License). Original worksheet.")

    def section_title(self, title, minutes, note=""):
        self.ensure(9 * mm + self.row_h)
        c = self.c
        lab = title.upper() + (f" · {minutes} min" if minutes else "")
        c.setFont("Helvetica-Bold", 8.5); c.drawString(self.ml, self.y - 8, lab)
        c.setLineWidth(0.6); c.rect(self.W - self.mr - 7, self.y - 9, 7, 7, stroke=1, fill=0)  # done box
        self.y -= 11
        if note:
            self.note(note, 7.3)

    def guides(self, base, x1=None):
        c, s = self.c, self.scale
        x0 = self.ml
        x1 = self.W - self.mr if x1 is None else x1
        top, mid, bot = base + self.font.asc * s, base + self.font.xh * s, base + self.font.desc * s
        c.saveState(); c.setStrokeColorRGB(0, 0, 0); c.setLineCap(1)
        if self.spec.get("slant_guides", True):
            w, dash = GUIDE["slant"]; c.setLineWidth(w); c.setDash(*dash)
            t = math.tan(math.radians(self.slant))
            step = self.spec.get("slant_spacing_mm", 9) * mm
            x = x0 - (top - bot) * t
            while x < x1:
                xa, ya, xb, yb = x, bot, x + (top - bot) * t, top
                if t and xa < x0: ya = bot + (x0 - xa) / t; xa = x0
                if t and xb > x1: yb = bot + (x1 - x) / t; xb = x1
                if xb > xa: c.line(xa, ya, xb, yb)
                x += step
            c.setDash()
        for y, kind in ((top, "outer"), (bot, "outer"), (mid, "mid"), (base, "base")):
            w, dash = GUIDE[kind]; c.setLineWidth(w)
            if dash: c.setDash(*dash)
            else: c.setDash()
            c.line(x0, y, x1, y)
        c.restoreState()

    def new_row(self, x_end=None):
        """x_end: if given, the guide lines stop there (hard cap on how much fits in the row)."""
        self.ensure(self.row_h)
        base = self.y - self.above
        self.guides(base, x_end)
        self.y -= self.row_h
        return base

    @staticmethod
    def _levels(fade, n):
        out = []
        for lvl, k in zip(["model", "trace", "faint"], fade):
            out += [lvl] * k
        return (out + ["blank"] * n)[:n]

    # ---- row kinds
    def row_repeat(self, unit, fade=(1, 2, 2), gap_x=1.4, max_cells=None):
        s = self.scale
        w = self.font.width(unit, s)
        gap = self.font.xh * s * gap_x
        n = max(1, int((self.tw - 3 + gap) // (w + gap)))
        if max_cells:
            n = min(n, max_cells)
        x_end = None
        if max_cells:   # hard cap: the guide lines end after the last cell, so nothing more fits
            x_end = min(self.W - self.mr, self.ml + 3 + n * (w + gap) + 1.5 * mm)
        base = self.new_row(x_end)
        x = self.ml + 3
        for lvl in self._levels(fade, n):
            self.font.draw(self.c, unit, x, base, s, lvl, self.skew)
            x += w + gap
        if x_end is not None and x_end < self.W - self.mr:
            self._stop_mark(x_end, base)

    def _stop_mark(self, x, base):
        c, s = self.c, self.scale
        c.saveState(); c.setStrokeColorRGB(0, 0, 0); c.setLineWidth(1.4); c.setLineCap(0)
        c.line(x, base + self.font.desc * s, x, base + self.font.asc * s)
        c.restoreState()

    def wrap_cursive(self, text):
        lines, cur = [], ""
        for word in text.split():
            t = (cur + " " + word).strip()
            if self.font.width(t, self.scale) <= self.tw - 5 or not cur:
                cur = t
            else:
                lines.append(cur); cur = word
        if cur: lines.append(cur)
        return lines

    def row_text(self, text, style="trace", copy_rows=1):
        for line in self.wrap_cursive(text):
            base = self.new_row()
            self.font.draw(self.c, line, self.ml + 3, base, self.scale, style, self.skew)
            for _ in range(copy_rows):
                self.new_row()

    def row_blank(self, n=1, width_pct=100):
        x_end = None
        if width_pct < 100:   # hard cap: guide lines end at this share of the text width, with a stop bar
            x_end = self.ml + self.tw * width_pct / 100.0
        for _ in range(n):
            base = self.new_row(x_end)
            if x_end is not None:
                self._stop_mark(x_end, base)

    def row_strokes(self, pattern, fade=(1, 2, 2), tall=False):
        base = self.new_row()
        s, c = self.scale, self.c
        h = (self.font.asc if tall else self.font.xh) * s
        t = math.tan(math.radians(self.slant))
        x0, x1 = self.ml + 3, self.W - self.mr - 3
        seg = h * 1.25
        unit_w = seg * 3.2 + h * 0.6
        levels = self._levels(fade, max(1, int((x1 - x0) // unit_w)))
        x = x0
        for lvl in levels:
            if lvl != "blank":
                c.saveState(); c.setStrokeColorRGB(0, 0, 0); c.setLineCap(1); c.setLineJoin(1)
                if lvl == "model": c.setLineWidth(1.0)
                elif lvl == "trace": c.setLineWidth(0.6); c.setDash(2.2, 1.4)
                else: c.setLineWidth(0.6); c.setDash(0.5, 1.6)
                p = c.beginPath()
                N = 160
                if pattern in ("oval_direct", "oval_indirect"):
                    # compact retraced ovals (Palmer-style drill); direct = counter-clockwise
                    turns, a = 6, h * 0.32
                    sign = 1 if pattern == "oval_direct" else -1
                    for i in range(N * turns + 1):
                        th = 2 * math.pi * i / N
                        u = a * math.cos(th) + (seg * 2.2) * i / (N * turns)
                        v = h / 2 + (h / 2) * math.sin(th * sign)
                        X, Y = x + a + u + v * t, base + v
                        (p.moveTo if i == 0 else p.lineTo)(X, Y)
                elif pattern == "push_pull":
                    k = 12
                    for i in range(k):
                        xx = x + i * seg * 2.8 / k
                        p.moveTo(xx, base); p.lineTo(xx + h * t, base + h)
                elif pattern == "wave":      # undercurve/overcurve rhythm
                    for i in range(N + 1):
                        u = seg * 3 * i / N
                        v = h / 2 - (h / 2) * math.cos(2 * math.pi * 3 * i / N)
                        X, Y = x + u + v * t, base + v
                        (p.moveTo if i == 0 else p.lineTo)(X, Y)
                c.drawPath(p, stroke=1, fill=0); c.restoreState()
            x += unit_w

    def note(self, text, size=7.5, bold=False):
        c = self.c
        f = "Helvetica-Bold" if bold else "Helvetica"
        lines = self._wrap(text, f, size, self.tw)
        self.ensure(len(lines) * (size + 1.8) + 2)
        c.setFont(f, size)
        for ln in lines:
            c.drawString(self.ml, self.y - size, ln); self.y -= size + 1.8
        self.y -= 2

    # ---- sections
    def section(self, sec):
        self.section_title(sec.get("title", sec.get("type", "")), sec.get("minutes"), sec.get("note", ""))
        for r in sec.get("rows", []):
            k = r.get("kind")
            if k == "repeat":
                self.row_repeat(r["unit"], r.get("fade", (1, 2, 2)), r.get("gap", 1.4), r.get("max"))
            elif k == "text":
                self.row_text(r["text"], r.get("style", "trace"), r.get("copy_rows", 1))
            elif k == "blank":
                self.row_blank(r.get("count", 1), r.get("width_pct", 100))
            elif k == "strokes":
                self.row_strokes(r["pattern"], r.get("fade", (1, 2, 2)), r.get("tall", False))
            elif k == "recall":
                # write-from-memory: no model on these rows, only the letter names in plain type
                self.note("From memory (don't look back at the model): " + r["prompt"], 7.5, True)
                self.row_blank(r.get("rows", 2), r.get("width_pct", 100))
            elif k == "mixed":
                # interleaved (random-order) practice of already-introduced letters/joins
                import random
                rnd = random.Random(r.get("seed", 1))
                items = list(r["items"]) if isinstance(r["items"], list) else list(r["items"])
                seq, prev = [], None
                for _ in range(r.get("length", 8)):
                    choice = rnd.choice([x for x in items if x != prev] or items)
                    seq.append(choice); prev = choice
                self.row_text(" ".join(seq), r.get("style", "model"), r.get("copy_rows", 1))
            elif k == "selfcheck":
                self.note("Self-check (1 min): circle your best " + r.get("what", "letter") +
                          ", put × under your worst; then write one thing to change tomorrow: "
                          "____________________________", 7.5)
            elif k == "note":
                if r.get("keep_rows"):   # keep this note on the same page as the next N guide rows
                    self.ensure(r["keep_rows"] * self.row_h + 24)
                self.note(r["text"], r.get("size", 7.5), r.get("bold", False))
            elif k == "timed":
                sec_ = r.get("seconds", 60)
                self.note(f"Timed copy, {sec_} s: write the line below as many times as you can at a brisk but "
                          f"comfortable pace. Words: ____ ÷ {sec_ / 60:g} min = ____ WPM. Legible to a stranger? Y / N")
                self.row_text(r["text"], "model", 0)
                self.row_blank(r.get("blank_rows", 3))
        self.y -= 3

    def build(self):
        for sec in self.spec.get("sections", []):
            self.section(sec)
        tip = self.spec.get("tip")
        if tip:
            lines = self._wrap("Tip: " + tip, "Helvetica-Oblique", 7.8, self.tw)
            self.ensure(len(lines) * 10 + 4)
            self.c.setLineWidth(0.5); self.c.line(self.ml, self.y - 1, self.W - self.mr, self.y - 1)
            self.c.setFont("Helvetica-Oblique", 7.8)
            for ln in lines:
                self.c.drawString(self.ml, self.y - 10, ln); self.y -= 10
        self.footer()
        self.c.save()
        return self.pages


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("spec"); ap.add_argument("-o", "--out")
    a = ap.parse_args()
    spec = json.load(open(a.spec))
    out = a.out or os.path.splitext(a.spec)[0] + ".pdf"
    pages = Sheet(spec, out).build()
    print(f"wrote {out} ({pages} page{'s' if pages > 1 else ''})")
    limit = spec.get("max_pages", 3)
    if pages > limit:
        print(f"WARNING: more than {limit} pages; trim the session spec.", file=sys.stderr)


if __name__ == "__main__":
    main()
