# bmp2c

Convert 1-bpp BMP files into MISRA-friendly C arrays for embedded displays, and emit 2-D matrices from folders — with deterministic formatting and explicit rules.

- Bit order in byte: LSB-first (bit 0 = first pixel in each 8-pixel group)
- Packing orientation: Row-major — pack pixels in runs of 8 horizontally
- Scan direction: Top-left origin; left-to-right within rows; rows top-to-bottom
- Foreground mapping: Black = 1, White = 0
- Input: 1-bpp BMP only by default; optional fixed-threshold binarization (128) via `--allow-threshold`
- Edits (pre-pack): invert, flip-h, flip-v, rotate 90/180/270 (clockwise), trim (auto-crop white), pad (L/R/T/B), draw (`--draw "x,y,set|clear"`)

No network access. Deterministic output. Library + CLI (`python -m bmp2c ...`).

---

## Exact Packing Definitions

### Row-major (default)

- For each row `y = 0..height-1`, iterate `x` in steps of 8: `x = 0, 8, 16, ...`.
- Build byte `b` where bit `i = 0..7` corresponds to pixel `(x+i, y)` if within bounds.
- Set bit `i` if the pixel is black (1). Bit 0 is the leftmost pixel of the 8-run.
- Total bytes = `ceil(width/8) * height`.

### Vertical pages (SSD1306-style)

If you need 8-pixel vertical bytes, use:

```
--pack page
```

- For each page `p = 0..ceil(height/8)-1`, set `y0 = p*8`.
- For `x = 0..width-1`, form a byte with bit `i = 0..7` = pixel at `(x, y0+i)` (1 if black, else 0).
- LSB is the top pixel; MSB is `y0+7`.
- Total bytes = `width * ceil(height/8)`.

---

## GUI Mode

A simple Tk/ttk GUI is included.

Run it with:

```
bmp2c-gui
# or:
bmp2c gui
# or:
python -m bmp2c.gui
```

- Browse File to convert a single BMP (1-bpp by default).
- Browse Folder to process a folder (per-file `.c` + a matrix); mixed sizes are grouped into separate matrices by default.
- Options mirror the CLI: pack (row/page), sort (alpha/natural), edits (invert, flip, rotate, trim, pad, draws), allow-threshold, emit-dims.
- Defaults: the GUI uses `pack=page` by default; output directory is optional and defaults next to the input.

---

## Notes

- The GUI runs work on a background thread and streams stdout/stderr to the log panel.
- Edit semantics match the CLI (e.g., non-1-bpp without `--allow-threshold` or out-of-bounds `--draw` raise errors). The GUI groups mixed sizes by default instead of failing.

---

## Run From Source (no install)

You can run directly from the repo without installing the package. Ensure Python 3.11+ is available and that the `Pillow` dependency is installed in your environment.

- Bash/Zsh:

```
export PYTHONPATH=src
python -m bmp2c.cli --help     # CLI
python -m bmp2c.gui            # GUI
```

- Windows PowerShell:

```
$env:PYTHONPATH = "src"
python -m bmp2c.cli --help     # CLI
python -m bmp2c.gui            # GUI
```

- Windows cmd.exe:

```
set PYTHONPATH=src
python -m bmp2c.cli --help     # CLI
python -m bmp2c.gui            # GUI
```

Tip: If `Pillow` is missing, either install it directly (`python -m pip install Pillow`) or use the editable install flow below to resolve all dependencies.

---

## Fresh Virtual Environment (editable)

Recommended for development: create a clean venv and install in editable mode.

- Bash/Zsh (Linux/macOS/Git Bash):

```
deactivate 2>/dev/null || true   # ignore if not active
rm -rf .venv
python -m venv .venv
source .venv/bin/activate
python -m pip install -U pip setuptools wheel
python -m pip install -e .

# Run GUI
bmp2c-gui
# If wrapper doesn’t open in your shell:
python -m bmp2c.gui

# CLI
bmp2c --help
# or:
python -m bmp2c.cli --help
```

- Windows PowerShell:

```
# Ignore if not active
deactivate
Remove-Item -Recurse -Force .venv -ErrorAction SilentlyContinue
python -m venv .venv
./.venv/Scripts/Activate.ps1
python -m pip install -U pip setuptools wheel
python -m pip install -e .

# Run GUI
bmp2c-gui
# If wrapper doesn’t open in your shell:
python -m bmp2c.gui

# CLI
bmp2c --help
# or:
python -m bmp2c.cli --help
```

Once installed (editable or regular), console scripts `bmp2c` and `bmp2c-gui` are available on your PATH.

---

## Self-test

Run the internal test suite from the CLI:

```
python -m bmp2c --selftest
```

---

## Generated C Header (attribution)

Generated `.c` files include a concise comment header with:

- Project link: `https://github.com/AlisonLuan/bmp2c`
- Generator and version: `bmp2c vX.Y.Z`
- “Generated — do not edit by hand” notice
- Author’s reminder to keep the repository link when sharing/redistributing

This follows common practice for code generators: include a short provenance banner so downstream users can trace the tool and version used.
