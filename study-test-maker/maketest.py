#!/usr/bin/env python3
"""maketest.py: turn a compact question file into a reMarkable-ready practice-test PDF
plus a private answer key.

Usage
  python3 maketest.py build TEST.txt [-o OUTDIR] [--with-key] [--preview]
  python3 maketest.py rng N [K] [--p 0.20]   # RNG answer letters for an in-chat set
  python3 maketest.py format                 # print the question-file format

What the script does, so the model never has to write it
  * layout: grayscale, portrait, wide margins, a confidence circle per item in the margin,
    items numbered 1) 2) ..., MC options a) b) ..., auto 1/2 columns, no item split across pages
  * shuffles every MC item's options with random.SystemRandom (lines marked '=' stay last)
  * writes '<name> KEY.md' (never put in the PDF unless --with-key) and prints a one-line key
  * escapes % & # _ outside math, and supports $math$, $$display$$, \\ce{...}, **bold**, ___ blanks
  * checks: one correct option per MC item, 4-6 options, duplicate options, missing images
Needs xelatex (TeX Live) with exam-free standard packages: fontspec, unicode-math, mhchem,
enumitem, multicol, needspace, tikz, graphicx, geometry, fancyhdr, siunitx.
"""
import argparse, datetime as dt, os, random, re, shutil, subprocess, sys, tempfile

FORMAT = r"""QUESTION FILE FORMAT (plain text, UTF-8). Header lines first, then items.

title: Ch. 5 Thermochemistry practice      (required; used in the file name)
course: CHEM 131                           (required; used in the file name)
date: 2026-10-28                           (optional; default today)
time: 25 min                               (optional; printed in the header)
notes: Periodic table provided. Units on every answer.   (optional instruction line)
cols: 2                                    (optional default for option columns: 1, 2 or auto)

## Part 1: no calorimetry        <- section heading (not numbered)
> Use the pedigree below for items 3-5.   <- unnumbered scenario/instruction paragraph
img: Pedigree10_12.png 9cm      <- image (path relative to this file, or absolute) + width

? How much heat does 15.0 g of water absorb from 25.0 °C to 55.0 °C? ($c = 4.184$ J/(g·°C))
* 1.88 kJ                        <- '* ' = correct option
- 0.188 kJ                       <- '- ' = distractor (dash + SPACE; '-3x' at a line start stays text)
- 18.8 kJ
- 4.18 kJ
= None of these                  <- '= ' fixed position (kept last); '=* ' = fixed AND correct
why: q = mcΔT = 15.0 × 4.184 × 30.0 = 1883 J      <- key only
tag: Ch5 q=mcΔT                  <- key only (topic, for the tracker)
space: 3                         <- work space in cm after the item (MC default 0, free response 4)
cols: 1                          <- per-item override

? Solve for $x$: $\dfrac{2x+1}{3} = \dfrac{x}{6} + 5$    <- no options = free response
key: x = 29/3                    <- key only
space: 6

page                             <- force a page break
Rules: '?' starts an item; following plain lines continue the stem (joined with spaces);
'\\' forces a line break. Blank lines and lines starting with '%' are ignored.
Math: $...$ inline, $$...$$ display; \dfrac for stacked fractions; \ce{H2SO4} for chemistry.
"""

HEAD = r"""\documentclass[11pt]{article}
\usepackage[letterpaper,top=0.8in,bottom=0.8in,left=0.9in,right=1.35in,marginparwidth=0.75in,marginparsep=0.15in]{geometry}
\usepackage{fontspec}
\usepackage{unicode-math}
\IfFontExistsTF{DejaVu Sans}{\setmainfont{DejaVu Sans}}{}
\IfFontExistsTF{DejaVu Math TeX Gyre}{\setmathfont{DejaVu Math TeX Gyre}}{}
\usepackage[version=4]{mhchem}
\usepackage{siunitx}
\usepackage{enumitem,multicol,needspace,graphicx,tikz,fancyhdr,xcolor,lastpage}
\setlength{\parindent}{0pt}
\setlength{\columnsep}{1.2em}
\pagestyle{fancy}\fancyhf{}\renewcommand{\headrulewidth}{0pt}
\fancyfoot[L]{\footnotesize\color{black!60}@@FOOT@@}
\fancyfoot[R]{\footnotesize\color{black!60}\thepage/\pageref{LastPage}}
\newcommand{\conf}{\marginpar{\centering\begin{tikzpicture}[baseline={([yshift=-0.6ex]current bounding box.center)}]\draw[line width=0.6pt] (0,0) circle (3.6mm);\node[below=3.6mm,font=\tiny,text=black!55] at (0,0) {conf 1--5};\end{tikzpicture}}}
\newcommand{\blank}{\underline{\hspace{2.6cm}}}
\begin{document}
"""


def esc(s):
    """Escape LaTeX specials outside math and \\ce{...}; light markdown."""
    out, i, n = [], 0, len(s)
    while i < n:
        if s.startswith('$$', i):
            j = s.find('$$', i + 2); j = n if j < 0 else j
            out.append(r'\[' + s[i + 2:j] + r'\]'); i = j + 2; continue
        if s[i] == '$':
            j = s.find('$', i + 1); j = n if j < 0 else j
            out.append(s[i:j + 1]); i = j + 1; continue
        if s.startswith(r'\ce{', i):
            depth, j = 0, i + 3
            while j < n:
                depth += s[j] == '{'; depth -= s[j] == '}'
                if depth == 0: break
                j += 1
            out.append(s[i:j + 1]); i = j + 1; continue
        if s.startswith('___', i):
            while i < n and s[i] == '_': i += 1
            out.append(r'\blank{}'); continue
        if s.startswith('**', i):
            j = s.find('**', i + 2)
            if j > 0:
                out.append(r'\textbf{' + esc(s[i + 2:j]) + '}'); i = j + 2; continue
        c = s[i]
        if s.startswith('\\\\', i):
            out.append('\\\\ '); i += 2; continue
        out.append({'%': r'\%', '&': r'\&', '#': r'\#', '_': r'\_', '^': r'\^{}'}.get(c, c)); i += 1
    return ''.join(out)


def parse(path):
    meta, items, cur = {}, [], None
    base = os.path.dirname(os.path.abspath(path))
    field = re.compile(r'^(space|img|cols|key|why|tag|pts):\s*(.*)$')
    with open(path, encoding='utf-8') as f:
        lines = f.read().splitlines()
    for ln_no, raw in enumerate(lines, 1):
        line = raw.rstrip()
        s = line.strip()
        if not s or s.startswith('%'):
            continue
        if not items and cur is None:
            m = re.match(r'^(title|course|date|time|notes|cols|name):\s*(.*)$', s)
            if m:
                meta[m.group(1)] = m.group(2).strip(); continue
        if s.startswith('? ') or s == '?':
            cur = {'kind': 'q', 'stem': s[1:].strip(), 'opts': [], 'line': ln_no}
            items.append(cur); continue
        if s.startswith('## '):
            items.append({'kind': 'h', 'text': s[3:].strip()}); cur = None; continue
        if s.startswith('> '):
            items.append({'kind': 'p', 'text': s[2:].strip()}); cur = None; continue
        if s == 'page':
            items.append({'kind': 'page'}); cur = None; continue
        m = re.match(r'^(=\*|\*|-|=)\s+(.+)$', s)
        if m and cur is not None and cur['kind'] == 'q':
            mk = m.group(1)
            cur['opts'].append({'text': m.group(2).strip(), 'ok': '*' in mk, 'fixed': mk.startswith('=')})
            continue
        m = field.match(s)
        if m:
            k, v = m.group(1), m.group(2).strip()
            target = cur if cur is not None else None
            if k == 'img':
                parts = v.rsplit(' ', 1)
                width = parts[1] if len(parts) == 2 and re.match(r'^[\d.]+(cm|in|mm)$', parts[1]) else None
                p = parts[0] if width else v
                p = p if os.path.isabs(p) else os.path.join(base, p)
                img = {'path': p, 'width': width or '8cm'}
                if target is None:
                    items.append({'kind': 'img', **img})
                else:
                    target.setdefault('imgs', []).append(img)
                continue
            if target is None:
                sys.exit(f'line {ln_no}: "{k}:" outside an item')
            target[k] = v; continue
        if cur is not None and not cur['opts']:
            cur['stem'] += ' ' + s; continue
        if cur is not None and cur['opts']:
            cur['opts'][-1]['text'] += ' ' + s; continue
        sys.exit(f'line {ln_no}: cannot place this line: {s[:60]}')
    for k in ('title', 'course'):
        if k not in meta:
            sys.exit(f'missing header "{k}:"')
    return meta, items


def check(items):
    warns, n = [], 0
    for it in items:
        if it['kind'] == 'img' and not os.path.exists(it['path']):
            warns.append(f'missing image {it["path"]}')
        if it['kind'] != 'q':
            continue
        n += 1
        for im in it.get('imgs', []):
            if not os.path.exists(im['path']):
                warns.append(f'{n}) missing image {im["path"]}')
        o = it['opts']
        if o:
            k = sum(x['ok'] for x in o)
            if k != 1:
                warns.append(f'{n}) has {k} correct options (need exactly 1)')
            if not 4 <= len(o) <= 6:
                warns.append(f'{n}) has {len(o)} options (tests use 4-6)')
            t = [x['text'].lower() for x in o]
            if len(set(t)) != len(t):
                warns.append(f'{n}) duplicate options')
        elif 'key' not in it:
            warns.append(f'{n}) free response without "key:"')
    return warns


def shuffle(items):
    rng = random.SystemRandom()
    for it in items:
        if it['kind'] == 'q' and it['opts']:
            free = [o for o in it['opts'] if not o['fixed']]
            fixed = [o for o in it['opts'] if o['fixed']]
            rng.shuffle(free)
            it['opts'] = free + fixed


def safe(s):
    return re.sub(r'[<>:"/\\|?*]+', '-', s).strip()


def build_tex(meta, items, imgdir, with_key):
    date = meta.get('date') or dt.date.today().isoformat()
    name = meta.get('name') or f"{date} {meta['course']} {meta['title']}"
    t = [HEAD.replace('@@FOOT@@', esc(name))]
    t.append(r'{\Large\bfseries ' + esc(meta['title']) + r'}\hfill{\large ' + esc(meta['course']) + r'}\\[3pt]')
    sub = [date] + ([meta['time']] if meta.get('time') else [])
    t.append(r'{\small ' + esc(' · '.join(sub)) + r'\hfill Start \underline{\hspace{1.6cm}}\quad Finish \underline{\hspace{1.6cm}}}\\[2pt]')
    if meta.get('notes'):
        t.append(r'{\small\itshape ' + esc(meta['notes']) + r'}\\')
    t.append(r'{\small\color{black!60} Rate each item 1--5 in its circle.}\par\medskip\hrule\medskip')
    defcols = meta.get('cols', 'auto')
    n, key = 0, []
    for idx, it in enumerate(items):
        k = it['kind']
        if k == 'h':
            t.append(r'\Needspace{5\baselineskip}\medskip{\large\bfseries ' + esc(it['text']) + r'}\par\smallskip')
        elif k == 'p':
            t.append(r'\Needspace{3\baselineskip}{\itshape ' + esc(it['text']) + r'}\par\smallskip')
        elif k == 'page':
            t.append(r'\newpage')
        elif k == 'img':
            dst = os.path.join(imgdir, f'img{idx}{os.path.splitext(it["path"])[1]}')
            if os.path.exists(it['path']):
                shutil.copy(it['path'], dst)
                t.append(r'\begin{center}\includegraphics[width=' + it['width'] + r',keepaspectratio]{' + dst + r'}\end{center}')
        elif k == 'q':
            n += 1
            o = it['opts']
            sp = float(it.get('space', '0' if o else '4') or 0)
            cols = it.get('cols', defcols)
            if cols == 'auto':
                cols = '2' if o and len(o) >= 4 and max(len(x['text']) for x in o) <= 24 else '1'
            need = 3 + (len(o) if cols == '1' else (len(o) + 1) // 2) + int(sp * 1.6)
            t.append(f'% Q{n}')
            t.append(r'\Needspace{' + str(min(need, 30)) + r'\baselineskip}')
            t.append(r'\begin{enumerate}[label=' + str(n) + r'),leftmargin=2.2em,itemsep=0pt,topsep=4pt]\item ' + r'\leavevmode\conf ' + esc(it['stem']))
            for im in it.get('imgs', []):
                dst = os.path.join(imgdir, f'q{n}_{len(os.listdir(imgdir))}{os.path.splitext(im["path"])[1]}')
                if os.path.exists(im['path']):
                    shutil.copy(im['path'], dst)
                    t.append(r'\par\smallskip{\centering\includegraphics[width=' + im['width'] + r',keepaspectratio]{' + dst + r'}\par}')
            if o:
                if cols != '1':
                    t.append(r'\begin{multicols}{' + cols + r'}\raggedcolumns')
                t.append(r'\begin{enumerate}[label=\alph*),itemsep=1pt,topsep=3pt,leftmargin=2em]')
                for j, x in enumerate(o):
                    t.append(r'\item ' + esc(x['text']))
                    if x['ok']:
                        key.append((n, 'abcdef'[j] if j < 6 else '?', x['text'], it))
                t.append(r'\end{enumerate}')
                if cols != '1':
                    t.append(r'\end{multicols}')
            else:
                key.append((n, 'FR', it.get('key', '(no key given)'), it))
            if sp:
                t.append(r'\vspace*{' + f'{sp}cm' + '}')
            t.append(r'\end{enumerate}\smallskip')
    if with_key:
        t.append(r'\newpage{\Large\bfseries Answer key}\par\medskip')
        for (q, letter, text, it) in key:
            extra = (' --- ' + esc(it['why'])) if it.get('why') else ''
            t.append(r'\textbf{' + str(q) + ')} ' + (letter + ') ' if letter != 'FR' else '') + esc(text) + extra + r'\par\smallskip')
    t.append(r'\end{document}')
    return name, '\n'.join(t), key


def compile_tex(tex, workdir):
    p = os.path.join(workdir, 'test.tex')
    open(p, 'w', encoding='utf-8').write(tex)
    for _ in range(2):  # 2 passes for page x/y
        r = subprocess.run(['xelatex', '-interaction=nonstopmode', '-halt-on-error', 'test.tex'],
                           cwd=workdir, capture_output=True, text=True)
        if r.returncode:
            log = open(os.path.join(workdir, 'test.log'), encoding='utf-8', errors='replace').read()
            msg = re.findall(r'^! .*', log, re.M)
            lm = re.search(r'^l\.(\d+)', log, re.M)
            where = ''
            if lm:
                src = tex.splitlines()[:int(lm.group(1))]
                qs = [l for l in src if l.startswith('% Q')]
                where = f' near item {qs[-1][3:]}' if qs else ' in the header'
            sys.exit(f'LaTeX error{where}: {msg[0] if msg else "see log"}')
    log = open(os.path.join(workdir, 'test.log'), encoding='utf-8', errors='replace').read()
    over = len(re.findall(r'Overfull \\hbox \((\d+\.\d+)pt', log))
    return os.path.join(workdir, 'test.pdf'), over


def cmd_build(a):
    meta, items = parse(a.file)
    warns = check(items)
    shuffle(items)
    out = a.outdir or os.path.dirname(os.path.abspath(a.file))
    os.makedirs(out, exist_ok=True)
    with tempfile.TemporaryDirectory() as wd:
        imgdir = os.path.join(wd, 'img'); os.makedirs(imgdir)
        name, tex, key = build_tex(meta, items, imgdir, a.with_key)
        pdf, over = compile_tex(tex, wd)
        fname = safe(name) + (' WITH KEY' if a.with_key else '') + '.pdf'
        dst = os.path.join(out, fname)
        shutil.copy(pdf, dst)
        pages = subprocess.run(['pdfinfo', dst], capture_output=True, text=True).stdout
        pages = re.search(r'Pages:\s+(\d+)', pages)
        if a.preview:
            subprocess.run(['pdftoppm', '-f', '1', '-l', '1', '-r', '50', '-png', dst,
                            os.path.join(out, safe(name) + ' preview')])
    kpath = os.path.join(out, safe(name) + ' KEY.md')
    with open(kpath, 'w', encoding='utf-8') as f:
        f.write(f'# KEY: {name}\n\n')
        for q, letter, text, it in key:
            tag = f" [{it['tag']}]" if it.get('tag') else ''
            why = f" | {it['why']}" if it.get('why') else ''
            f.write(f'{q}) {letter}: {text}{tag}{why}\n')
    print(f'PDF: {dst} ({pages.group(1) if pages else "?"} pp, {len(key)} items)')
    print(f'KEY: {kpath}')
    print('KEY LINE: ' + ' '.join(f'{q}{l}' for q, l, _, _ in key))
    if over:
        print(f'note: {over} overfull line(s), probably a long unbreakable formula; check visually if it matters')
    for w in warns:
        print('WARN:', w)


def cmd_rng(a):
    r = random.SystemRandom()
    print(' '.join(f'{i})' + 'abcdef'[r.randrange(a.k)] for i in range(1, a.n + 1)),
          '|', 'EXPLORE' if r.random() < a.p else 'EXPLOIT')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest='cmd')
    b = sp.add_parser('build'); b.add_argument('file'); b.add_argument('-o', '--outdir')
    b.add_argument('--with-key', action='store_true', help='append a key page (friend copies only)')
    b.add_argument('--preview', action='store_true', help='also write a 50-dpi PNG of page 1')
    r = sp.add_parser('rng'); r.add_argument('n', type=int); r.add_argument('k', type=int, nargs='?', default=5)
    r.add_argument('--p', type=float, default=0.20)
    sp.add_parser('format')
    a = ap.parse_args()
    if a.cmd == 'build': cmd_build(a)
    elif a.cmd == 'rng': cmd_rng(a)
    elif a.cmd == 'format': print(FORMAT)
    else: ap.print_help()


if __name__ == '__main__':
    main()
