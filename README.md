# bmp2c

Convert **1-bpp BMP** files into **MISRA-friendly C** arrays for embedded displays, and emit **2-D matrices** from folders — with deterministic formatting and robust, explicit rules.

- **Bit order in byte:** **LSB_FIRST** (bit 0 = first pixel of the packed group)
- **Packing orientation:** **Row-major (“Linha/Row”)** — pack pixels in runs of 8 horizontally
- **Scan direction:** **Top-left origin**, iterate left→right within rows, rows top→bottom
- **Foreground mapping:** **Black = 1**, White = 0
- **Input:** **1-bpp BMP only by default**; optional fixed-threshold binarization (128) via `--allow-threshold`
- **Edits (pre-pack):** invert, flip-h, flip-v, rotate 90/180/270 (clockwise), trim (auto-crop white), pad (L/R/T/B), draw (`--draw "x,y,set|clear"`)

No network access. Deterministic output. Library + CLI (`python -m bmp2c ...`).

---

## Exact packing definition

(undocumented)

### Alternative packing: vertical pages (SSD1306-style)

If you need display “page” format (8-pixel vertical bytes), use:

```
--pack page
```

Definition:

- For each page `p = 0..ceil(height/8)-1`, set `y0 = p*8`.
- For `x = 0..width-1`, form a byte with:
  - bit `i=0..7` = pixel at `(x, y0+i)` (1 if black, else 0).
- LSB is the **top** pixel, MSB is **y0+7**.

Total bytes = `width * ceil(height/8)`.

---

### GUI mode

A simple Tk/ttk GUI is included.

Run it with:

```bash
bmp2c-gui
# or:
bmp2c gui
# or:
python -m bmp2c.gui
```

Click Browse File… to convert a single BMP (1-bpp by default).

Click Browse Folder… to process a folder (per-file .c + matrix).

Options mirror the CLI: pack (row/page), sort (alpha/natural), edits (invert, flip, rotate, trim, pad, draws), allow-threshold, emit-dims.

Output directory is optional; defaults next to the input.

---

## Notes

- The GUI runs work on a **background thread** and streams stdout/stderr to the log panel.
- It accepts the same edit semantics and failure conditions as the CLI (e.g., non-1-bpp without `allow-threshold`, mixed sizes when grouping is off, OOB `--draw`).

---

## One thing I couldn’t mirror exactly

You said “Copy the interface from the picture in the annex.” I don’t have that image in this chat, so I matched the **controls and layout** functionally (file/folder pickers, options grouped, progress, log). If you need the **exact visual** (spacing/colors/icons), please share the screenshot or list specific tweaks (font sizes, alignment, button labels), and I’ll adjust the widgets/layout to match precisely.
