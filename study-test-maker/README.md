# study-test-maker

You write the questions in a short plain-text file. `maketest.py` turns that file into a
practice-test PDF formatted for a reMarkable tablet, plus a separate answer key.

The model writes only the question content. The script handles the layout, the shuffling of answer
positions and the key, so building a test costs far fewer output tokens than writing LaTeX or
reportlab code from scratch each time.

## Use (in a Claude cloud session)

```bash
curl -sSLO https://raw.githubusercontent.com/claudesalaver/cursive-tools/main/study-test-maker/maketest.py
python3 maketest.py format                     # prints the question-file format (read once)
python3 maketest.py build mytest.txt -o out    # PDF + "<name> KEY.md" + one-line key on stdout
python3 maketest.py build mytest.txt --with-key  # copy WITH a key page (for a friend, never the tablet)
python3 maketest.py rng 5 5                    # RNG answer letters for an in-chat set of five + EXPLORE/EXPLOIT
```

## What you get

- Grayscale portrait letter page with wide margins. Each item has a confidence circle in the margin.
- Items are numbered `1)` and options are lettered `a)`. Options go into one or two columns
  automatically, and an item is never split across a page.
- Every MC item's options are shuffled with `random.SystemRandom`. Options written with a leading
  `=` (such as "None of these") stay last.
- The file name is `YYYY-MM-DD <course> <title>.pdf`.
- The key goes to a separate `KEY.md` file and stays out of the PDF.
- Checks: each MC item has exactly one correct option and 4–6 options in total, no duplicate
  options, no missing images, and every free-response item has a key.
- Math is written as `$...$` or `$$...$$`, and `\dfrac` gives stacked fractions. Chemistry uses
  `\ce{H2SO4}` (mhchem). The characters `% & # _` are escaped automatically.

Requires `xelatex` (TeX Live). It is pre-installed in Claude cloud sessions.

See `examples/example-test.txt`.
