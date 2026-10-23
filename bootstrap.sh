#!/usr/bin/env bash
# One command at the start of a session: install dependencies and fetch the latest tools.
# First time in a fresh sandbox:  git clone --depth 1 <REPO_URL> /home/claude/cursive-tools && bash /home/claude/cursive-tools/bootstrap.sh
# Later in the same session:      bash /home/claude/cursive-tools/bootstrap.sh
set -e
D="$(cd "$(dirname "$0")" && pwd)"
pip install -q --break-system-packages uharfbuzz fonttools reportlab scikit-image pillow numpy pymupdf 2>&1 | grep -v -i warning || true
if [ -d "$D/.git" ]; then git -C "$D" pull -q || true; fi
mkdir -p "$D/fonts" "$D/out"
python3 -I -c "import uharfbuzz, fontTools, reportlab, skimage, PIL, numpy, pymupdf; print('deps ok')"
echo "tools in $D"
