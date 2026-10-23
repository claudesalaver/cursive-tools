#!/usr/bin/env python3
"""
Compact session spec -> full worksheet spec -> PDF (+ QA + preview images).

    python3 build_session.py spec.json [-o OUTDIR] [--no-trim]

A spec with a "sections" key is treated as an old-style full spec and passed straight to the generator.
Compact format: see README.md. Letter stroke descriptions live in letters.json.

If the sheet runs over max_pages, the builder drops the lowest-priority rows (see _p) and rebuilds
until it fits, and prints what it dropped.
"""
import argparse, copy, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault("CURSIVE_FONT_DIR", os.path.join(HERE, "fonts"))
sys.path.insert(0, HERE)
import make_worksheet as mw
from fontTools.pens.boundsPen import BoundsPen

# one CursiveFont per font key: the dotted-trace skeletons are expensive, so cache them across rebuilds
_FONTS, _orig = {}, mw.CursiveFont
def _cached(key):
    if key not in _FONTS:
        _FONTS[key] = _orig(key)
    return _FONTS[key]
mw.CursiveFont = _cached

LETTERS = json.load(open(os.path.join(HERE, "letters.json"), encoding="utf-8"))

SHAKE = "Shake-out: drop the pen, shake the hand loose for 10 seconds, open and close the fingers 5 times."
WARM = ("Tick the grip box first. Ovals: big (they fill the band from baseline to top line), count 1-2-3-4-5-6 aloud, "
        "one count per turn, keep the pen on the page for all six turns. Move from the forearm, fingers still, "
        "lighter than feels natural. Row 1 has a model and dots; the rest are freehand.")
FATIGUE = " If your hand cramps or effort reaches 4, stop at the end of page 2 and write it in 'Hardest'."
CAP_RULE = ("Rule for this section: {cap} letters per row, count them, stop at the bar. Squeezing letters narrower "
            "to fit more is the problem; give each letter its full width.")
CHECK_SENTENCE = "Quick zephyrs blow, vexing daft Jim; my handwriting improves every day."


def height_hint(font, ch):
    g = font.tt.getBestCmap().get(ord(ch))
    if not g:
        return ""
    bp = BoundsPen(font.gs); font.gs[g].draw(bp)
    if not bp.bounds:
        return ""
    top, bot = bp.bounds[3] / font.xh, bp.bounds[1] / font.xh
    s = f"model height {top:.1f}x x-height" + (", descends below the baseline" if bot < -0.4 else "")
    return f" ({s})"


def expand(spec):
    """Compact spec -> full spec for make_worksheet.Sheet."""
    font = _cached(spec.get("font", "trad"))
    n = spec["session"]
    cap = spec.get("cap", 5)
    groups = spec.get("groups")
    if groups is None:
        groups = []
        if spec.get("new"):
            groups.append({"title": "New letters: " + " ".join(spec["new"]), "new": spec["new"]})
        if spec.get("again"):
            groups.append({"title": "Second exposure: " + " ".join(spec["again"]), "again": spec["again"]})
    sections = []

    # warm-up
    wu = spec.get("warmup", {})
    rows = [{"kind": "strokes", "pattern": "oval_direct", "fade": [1, 1, 0], "tall": True}]
    for i in range(wu.get("freehand_rows", 2)):
        rows.append({"kind": "strokes", "pattern": "oval_direct", "fade": [0, 0, 0], "tall": True,
                     "_p": 3 if i >= 2 else 0})
    rows.append({"kind": "note", "text": SHAKE})
    note = wu.get("note", WARM) + (FATIGUE if wu.get("fatigue_note", True) else "")
    sections.append({"title": wu.get("title", "Warm-up"), "minutes": wu.get("minutes", 4), "note": note, "rows": rows})

    # letter groups
    def letter_note(ch, fixes):
        lib = LETTERS.get(ch)
        if not lib:
            raise SystemExit(f"letters.json has no entry for '{ch}': add one (check the glyph first).")
        txt = lib["desc"]
        if fixes.get(ch):
            txt += " " + fixes[ch]
        if not lib.get("dotted"):
            txt += height_hint(font, ch)
        return {"kind": "note", "text": txt, "keep_rows": 3}

    for g in groups:
        fixes = {**spec.get("fix", {}), **g.get("fix", {})}
        new, again, double = g.get("new", []), g.get("again", []), set(g.get("double", []))
        allc = list(new) + list(again)
        rows = []
        for idx, ch in enumerate(allc):
            rows.append(letter_note(ch, fixes))
            lib = LETTERS[ch]
            if ch in new:
                first = [1, 2, 0] if lib.get("trace", True) else [2, 0, 0]
                rows.append({"kind": "repeat", "unit": ch, "fade": first, "max": cap})
                rows.append({"kind": "repeat", "unit": ch, "fade": [1, 0, 0], "max": cap})
            else:
                if ch in double:
                    rows.append({"kind": "repeat", "unit": ch, "fade": [2, 0, 0], "max": cap})
                rows.append({"kind": "repeat", "unit": ch, "fade": [1, 0, 0], "max": cap, "_p": 5 if ch not in double else 0})
            if len(allc) >= 4 and idx == len(allc) // 2 - 1:
                rows.append({"kind": "note", "text": SHAKE + " Check the grip box: still middle?"})
        if g.get("contrast"):
            rows.append({"kind": "note", "keep_rows": 2,
                         "text": g.get("contrast_note", "Contrast row: " + " and ".join(allc) + " alternate. Copy the line, "
                                 "then write your own. Check the heights of each pair against the guide lines.")})
            rows.append({"kind": "mixed", "items": "".join(allc), "length": 6, "seed": n, "style": "model", "copy_rows": 1})
        rows.append({"kind": "recall", "prompt": "   ".join(allc) if len(allc) > 2 else "   ".join(allc * 2),
                     "rows": 1, "width_pct": 55, "_p": 4 if g.get("contrast") else 0})
        gnote = g.get("note", CAP_RULE.format(cap=cap) if g is groups[0] or g.get("cap_rule") else "")
        mins = g.get("minutes", max(3, round(2.5 * len(new) + 1.5 * len(again))))
        sections.append({"title": g.get("title", "Letters"), "minutes": mins, "note": gnote, "rows": rows})

    # mixed
    mx = spec.get("mixed")
    if mx is None and spec.get("known"):
        mx = {"items": spec["known"]}
    if mx:
        sections.append({"title": "Mixed", "minutes": 3, "note": mx.get("note", ""), "rows": [
            {"kind": "mixed", "items": mx["items"], "length": mx.get("length", 8), "seed": mx.get("seed", n),
             "style": "model", "copy_rows": 1, "_p": 6}]})

    # words
    words = spec.get("words", [])
    if words:
        sections.append({"title": "Application", "minutes": 3,
                         "note": spec.get("words_note", "Short words from letters you know. Copy once under each line."),
                         "rows": [{"kind": "text", "text": w, "style": "model", "copy_rows": 1, "_p": 8 + i if i else 0}
                                  for i, w in enumerate(words)]})

    for s in spec.get("extras", []):
        sections.append(s)

    # checkpoint (every 7th session unless overridden)
    if spec.get("checkpoint", n % 7 == 0):
        sections.append({"title": "Checkpoint", "minutes": 5,
                         "note": "Standard checkpoint sentence, same size every time. Write it on each line below at your natural "
                                 "pace, no tracing. This page is compared with the baseline and earlier checkpoints.",
                         "rows": [{"kind": "note", "text": CHECK_SENTENCE, "bold": True, "size": 9},
                                  {"kind": "blank", "count": 4}]})

    # review
    rv = spec.get("review", {})
    rows = []
    if rv.get("oval_check"):
        rows.append({"kind": "strokes", "pattern": "oval_direct", "fade": [0, 0, 0], "tall": True, "_p": 1})
    for r in rv.get("recall", []):
        rows.append({"kind": "recall", "prompt": r, "rows": 1, "width_pct": 55})
    sc = spec.get("selfcheck") or (groups[0].get("new", groups[0].get("again", ["e"]))[0] if groups else "letter")
    rows.append({"kind": "selfcheck", "what": sc})
    rows.append({"kind": "note", "text": "Before you close the page: write your End time and effort in the header.", "bold": True})
    sections.append({"title": "Review", "minutes": 3, "note": rv.get("note", ""), "rows": rows})

    full = {k: spec[k] for k in ("session", "date", "focus", "font", "page", "xheight_mm", "extra_slant_deg",
                                 "slant_guides", "max_pages", "stage", "row_gap_mm") if k in spec}
    full.setdefault("font", "trad"); full.setdefault("page", "rm2"); full.setdefault("xheight_mm", 5)
    full.setdefault("extra_slant_deg", 16); full.setdefault("slant_guides", True); full.setdefault("max_pages", 3)
    full.setdefault("focus", " ".join(g.get("title", "") for g in groups))
    full["sections"] = sections
    if spec.get("tip"):
        full["tip"] = spec["tip"]
    return full


def strip_private(full):
    out = copy.deepcopy(full)
    for s in out["sections"]:
        for r in s.get("rows", []):
            r.pop("_p", None)
    return out


def build(full, pdf, trim=True):
    """Build; if over max_pages drop lowest-priority rows (highest _p) and retry. Returns (pages, dropped)."""
    full = copy.deepcopy(full)
    dropped = []
    while True:
        pages = mw.Sheet(strip_private(full), pdf).build()
        if pages <= full.get("max_pages", 3) or not trim:
            return pages, dropped, full
        cands = [(r.get("_p", 0), si, ri) for si, s in enumerate(full["sections"]) for ri, r in enumerate(s["rows"])
                 if r.get("_p", 0) > 0]
        if not cands:
            return pages, dropped, full
        _, si, ri = max(cands)
        r = full["sections"][si]["rows"].pop(ri)
        dropped.append(f"{full['sections'][si]['title']}: {r.get('kind')} {r.get('unit') or r.get('text') or r.get('prompt') or ''}".strip())
        if not full["sections"][si]["rows"]:
            full["sections"].pop(si)


def qa(pdf, outdir, stem):
    import pymupdf
    d = pymupdf.open(pdf)
    msgs, bad = [], False
    w, h = d[0].rect.width, d[0].rect.height
    if abs(w - mw.RM2[0]) > 1 or abs(h - mw.RM2[1]) > 1:
        msgs.append(f"page size {w:.0f}x{h:.0f} is not rM2"); bad = True
    cols = set()
    for p in d:
        for dr in p.get_drawings():
            for k in ("color", "fill"):
                c = dr.get(k)
                if c is not None and tuple(round(x, 2) for x in c) != (0.0, 0.0, 0.0):
                    cols.add(tuple(round(x, 2) for x in c))
            r = dr["rect"]
            if r.x0 < -1 or r.y0 < -1 or r.x1 > p.rect.x1 + 1 or r.y1 > p.rect.y1 + 1:
                msgs.append(f"drawing outside page on p.{p.number + 1}"); bad = True
        for b in p.get_text("dict")["blocks"]:
            for l in b.get("lines", []):
                for s in l["spans"]:
                    if s["color"] != 0:
                        cols.add(("text", s["color"]))
    if cols:
        msgs.append(f"non-black colours: {sorted(cols, key=str)}"); bad = True
    last = d[-1]
    ymax = max([dr["rect"].y1 for dr in last.get_drawings()] + [0])
    msgs.append(f"{len(d)} page(s); last page content reaches {100 * ymax / last.rect.height:.0f}% of its height")
    # preview: all pages side by side in one image
    from PIL import Image
    ims = []
    for p in d:
        pm = p.get_pixmap(dpi=75)
        ims.append(Image.frombytes("RGB", (pm.width, pm.height), pm.samples))
    sheet = Image.new("RGB", (sum(i.width for i in ims) + 8 * (len(ims) - 1), ims[0].height), "white")
    x = 0
    for i in ims:
        sheet.paste(i, (x, 0)); x += i.width + 8
    path = os.path.join(outdir, stem + "_preview.png")
    sheet.save(path)
    msgs.append(f"preview: {path}")
    return bad, msgs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("spec"); ap.add_argument("-o", "--outdir", default="out"); ap.add_argument("--no-trim", action="store_true")
    a = ap.parse_args()
    spec = json.load(open(a.spec, encoding="utf-8"))
    os.makedirs(a.outdir, exist_ok=True)
    full = spec if "sections" in spec else expand(spec)
    stem = f"Cursive S{int(full['session']):02d} - {full.get('focus', '').strip()}"[:90]
    pdf = os.path.join(a.outdir, stem + ".pdf")
    pages, dropped, final = build(full, pdf, trim=not a.no_trim)
    print("wrote", pdf)
    if dropped:
        print("over the page limit; dropped:", "; ".join(dropped))
    if pages > final.get("max_pages", 3):
        print(f"WARNING: {pages} pages, limit {final.get('max_pages', 3)}")
    bad, msgs = qa(pdf, a.outdir, stem)
    for m in msgs:
        print(("FAIL: " if bad and ("colour" in m or "outside" in m or "size" in m) else "") + m)
    json.dump(strip_private(final), open(os.path.join(a.outdir, stem + ".full.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
