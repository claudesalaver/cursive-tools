# cursive-tools

Worksheet generator and session builder for the cursive course (reMarkable 2, pure black, 157.8 x 210.4 mm).
Fonts: Playwrite US Trad etc. (SIL OFL), downloaded from github.com/google/fonts on first run.

## Start of a session (one command)
```
git clone --depth 1 <REPO_URL> /home/claude/cursive-tools && bash /home/claude/cursive-tools/bootstrap.sh
```

## Build a worksheet
```
python3 -W ignore /home/claude/cursive-tools/build_session.py sessions/s06.json -o /home/claude/out
```
Writes the PDF, a one-image preview of all pages (look at it once), a `.full.json`, and prints QA
(page count, rM2 size, black only, nothing outside the page). Exit code 1 on a QA failure. If the sheet is
over `max_pages` it drops the lowest-priority rows itself and says which.

## Compact session spec (JSON)
```json
{
 "session": 6, "date": "2026-10-23", "stage": "Stage 3 · Lowercase",
 "focus": "b h k f", "known": "bhkfelrsiutw",
 "groups": [
  {"title": "New letters: b h k f", "new": ["b","h","k","f"]},
  {"title": "Second exposure: e l", "again": ["e","l"], "double": ["e"], "contrast": true,
   "fix": {"e": "one extra sentence for this session"}}
 ],
 "mixed": {"items": "bhkfelrs", "length": 8, "seed": 6},
 "words": ["tell less leer este"],
 "review": {"oval_check": true, "recall": ["w   t   i   u"], "note": "text"},
 "selfcheck": "b",
 "tip": "one to three lines"
}
```
Per-group keys: `title`, `new` (first exposure: model+dots row, model+copy row, recall), `again` (model+copy row, recall),
`double` (letters that get an extra model row), `contrast` (alternating-letter row), `fix` (letter -> extra sentence),
`note`, `minutes`. Top level: `cap` (letters per row, default 5), `warmup` ({freehand_rows, note, fatigue_note}),
`checkpoint` (auto on every 7th session; true/false overrides), `extras` (raw sections), `known`, `font`, `xheight_mm`,
`extra_slant_deg`, `max_pages`. A spec that has a `sections` key is a full old-style spec and is passed straight through.

## Letter library
`letters.json`: one stroke description per letter. The builder stops with a message if a letter is missing.
Add it the first time the letter is used, after checking its glyph. The builder appends the measured model
height (x-height multiples) to every non-dotted letter note, so descriptions stay consistent with the font.

## Looking at returned work
```
python3 render.py file.pdf --pages 1-3 --dpi 90 --sheet      # all pages in one image
python3 render.py file.pdf --pages 2 --crop 8,60,150,120     # zoom on a region (mm)
```

## Files
`make_worksheet.py` generator (row kinds in the docstring and in the project's worksheet_spec.md) ·
`build_session.py` compact spec -> PDF + QA · `letters.json` · `render.py` · `bootstrap.sh` ·
`tests/s05_compact.json` example (rebuilds the delivered S5).

Unsure/open: the checkpoint page format (sentence + 4 blank rows) was not defined in the course docs; it is my
interpretation. Effort and time are not tracked by the tools.
