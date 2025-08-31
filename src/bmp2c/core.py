from __future__ import annotations

import io
import os
import re
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple

from PIL import Image

from .formatting import format_bytes_as_c_array, sanitize_symbol, upper_macro
from .ops import BitGrid, EditOptions, apply_edits


class Bmp2CError(Exception):
    """User-facing one-line errors."""


@dataclass(frozen=True)
class ImageResult:
    symbol: str
    width: int
    height: int
    data: bytes
    source_path: Path


def _read_bmp_bitcount(path: Path) -> int:
    with path.open("rb") as f:
        head = f.read(32)
    if len(head) < 30 or head[:2] != b"BM":
        raise Bmp2CError(f"Not a BMP file: {path}")
    bpp = struct.unpack_from("<H", head, 28)[0]
    return int(bpp)


def _bits_from_image(img: Image.Image, allow_threshold: bool, src: Path) -> BitGrid:
    if img.mode == "1":
        w, h = img.size
        px = img.load()
        out: BitGrid = []
        for y in range(h):
            row = []
            for x in range(w):
                v = px[x, y]  # 0 or 255
                row.append(1 if v == 0 else 0)  # black=1, white=0
            out.append(row)
        return out

    if not allow_threshold:
        raise Bmp2CError(
            f"Input is not 1-bpp: {src.name}. Pass --allow-threshold to binarize at 128."
        )

    gray = img.convert("L")
    w, h = gray.size
    px = gray.load()
    out2: BitGrid = []
    for y in range(h):
        row = []
        for x in range(w):
            row.append(1 if px[x, y] < 128 else 0)  # black if < 128
        out2.append(row)
    return out2


def pack_row_major_lsb_first(bits: BitGrid) -> bytes:
    height = len(bits)
    width = len(bits[0]) if height > 0 else 0
    if width == 0 or height == 0:
        return b""

    out = bytearray()
    for y in range(height):
        row = bits[y]
        x = 0
        while x < width:
            b = 0
            for i in range(8):
                xi = x + i
                if xi < width and row[xi] == 1:
                    b |= (1 << i)
            out.append(b)
            x += 8
    return bytes(out)


def pack_page_vertical_lsb_first(bits: BitGrid) -> bytes:
    """
    Page mode (SSD1306-style):
    - Height processed in pages of 8 rows: page = 0..ceil(h/8)-1
    - For each page, iterate x = 0..w-1
    - Byte bits i=0..7 map to (x, page*8 + i), LSB = top
    """
    height = len(bits)
    width = len(bits[0]) if height > 0 else 0
    if width == 0 or height == 0:
        return b""

    pages = (height + 7) // 8
    out = bytearray()
    for page in range(pages):
        y0 = page * 8
        for x in range(width):
            b = 0
            for i in range(8):
                yi = y0 + i
                if yi < height and bits[yi][x] == 1:
                    b |= (1 << i)
            out.append(b)
    return bytes(out)


def bytes_per_image(width: int, height: int, pack_kind: str = "row") -> int:
    if pack_kind == "row":
        return ((width + 7) // 8) * height
    if pack_kind == "page":
        return width * ((height + 7) // 8)
    raise ValueError(f"unknown pack_kind: {pack_kind!r}")


def _pack_desc(pack_kind: str) -> str:
    if pack_kind == "row":
        return "Row-major, LSB-first"
    if pack_kind == "page":
        return "Vertical pages (8px), LSB-first"
    return pack_kind


def _emit_header_comment(
    symbol: str, width: int, height: int, total_bytes: int, tool_version: str, pack_desc: str
) -> str:
    lines = [
        "/* =========================================================================",
        f" *  File: {symbol}.c",
        f" *  Desc: Auto-generated from BMP (1-bpp). Packing: {pack_desc}.",
        " *        Scan: top-left \u2192 left-to-right, top-to-bottom. Black=1.",
        f" *        Size: {width}x{height} px. Bytes: {total_bytes}.",
        " *  Notes: Generated to align with MISRA C:2004/2008 guidelines (style/comments).",
        f" *  Tool : bmp2c v{tool_version}",
        " *  Repo : https://github.com/AlisonLuan/bmp2c",
        " *  Gen  : This file is generated — do not edit by hand.",
        " *  Reminder (author): Please keep the repository link in this header when sharing/redistributing.",
        " * ========================================================================= */",
        "",
        "#include <stdint.h>  /* for uint8_t */",
        "",
        "/* Image data */",
    ]
    return "\n".join(lines)


def generate_c_single(
    symbol: str,
    width: int,
    height: int,
    data: bytes,
    emit_dims: bool,
    tool_version: str,
    pack_kind: str = "row",
) -> str:
    header = _emit_header_comment(
        symbol, width, height, len(data), tool_version, _pack_desc(pack_kind)
    )
    body_open = f"const unsigned char {symbol}[{len(data)}] =\n{{\n"
    arr = format_bytes_as_c_array(data)
    body_close = "\n};\n"
    dims = ""
    if emit_dims:
        up = upper_macro(symbol)
        dims = (
            "\n/* Optional (only if --emit-dims): */\n"
            f"#define {up}_WIDTH   {width}\n"
            f"#define {up}_HEIGHT  {height}\n"
        )
    return header + "\n" + body_open + arr + body_close + dims


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def process_single_image(
    input_path: Path,
    out_dir: Path | None,
    symbol_override: str | None,
    emit_dims: bool,
    allow_threshold: bool,
    edits: EditOptions,
    tool_version: str,
    verbose: bool = False,
    pack_kind: str = "row",
) -> ImageResult:
    if not input_path.exists():
        raise Bmp2CError(f"File not found: {input_path}")

    bpp = _read_bmp_bitcount(input_path)
    if bpp != 1 and not allow_threshold:
        raise Bmp2CError(
            f"Input is not 1-bpp (bpp={bpp}): {input_path.name}. Pass --allow-threshold."
        )

    img = Image.open(input_path)
    bits = _bits_from_image(img, allow_threshold=allow_threshold, src=input_path)
    bits = apply_edits(bits, edits)

    h = len(bits)
    w = len(bits[0]) if h > 0 else 0

    if pack_kind == "row":
        data = pack_row_major_lsb_first(bits)
    elif pack_kind == "page":
        data = pack_page_vertical_lsb_first(bits)
    else:
        raise Bmp2CError(f"Unknown --pack: {pack_kind}")

    symbol = sanitize_symbol(symbol_override or input_path.stem)
    content = generate_c_single(symbol, w, h, data, emit_dims, tool_version, pack_kind=pack_kind)

    out_dir_final = out_dir or input_path.parent
    out_path = out_dir_final / f"{symbol}.c"
    write_text(out_path, content)
    if verbose:
        print(f"Wrote {out_path} ({len(data)} bytes)")

    return ImageResult(symbol=symbol, width=w, height=h, data=data, source_path=input_path)


def _matrix_header_comment(
    base: str, width: int, height: int, count: int, bpi: int, version: str, pack_desc: str
) -> str:
    lines = [
        "/* =========================================================================",
        f" *  File: {base}_Matrix.c",
        f" *  Desc: Auto-generated BMP matrix. Packing: {pack_desc}.",
        " *        Scan: top-left \u2192 left-to-right, top-to-bottom. Black=1.",
        f" *        Size: {width}x{height} px per image. Count: {count}. Bytes/img: {bpi}.",
        " *  Notes: Generated to align with MISRA C:2004/2008 guidelines (style/comments).",
        f" *  Tool : bmp2c v{version}",
        " *  Repo : https://github.com/AlisonLuan/bmp2c",
        " *  Gen  : This file is generated — do not edit by hand.",
        " *  Reminder (author): Please keep the repository link in this header when sharing/redistributing.",
        " * ========================================================================= */",
        "",
        "#include <stdint.h>",
        "",
    ]
    return "\n".join(lines)


def generate_c_matrix(
    matrix_basename: str,
    entries: Sequence[ImageResult],  # all same WxH
    emit_dims: bool,
    version: str,
    pack_kind: str = "row",
) -> str:
    assert entries, "entries required"
    width = entries[0].width
    height = entries[0].height
    bpi = bytes_per_image(width, height, pack_kind=pack_kind)
    header = _matrix_header_comment(
        matrix_basename, width, height, len(entries), bpi, version, _pack_desc(pack_kind)
    )

    body_open = (
        f"const unsigned char {matrix_basename}_Matrix[{len(entries)}][{bpi}] =\n{{\n"
    )

    lines: List[str] = []
    for e in entries:
        comment = f"    /* name: {e.source_path.name} */ "
        arr = format_bytes_as_c_array(e.data)
        lines.append(comment + "{\n" + arr + "\n    }")

    body = ",\n".join(lines) + "\n};\n"

    macros = ""
    if emit_dims:
        up = upper_macro(matrix_basename)
        macros = (
            f"\n#define {up}_COUNT {len(entries)}\n"
            f"#define {up}_W     {width}\n"
            f"#define {up}_H     {height}\n"
            f"#define {up}_BPI   {bpi}\n"
        )
    return header + "\n" + body_open + body + macros


def _alpha_key(stem: str) -> tuple[str, str]:
    return (stem.casefold(), stem)


def _natural_key(stem: str) -> tuple:
    parts = re.split(r"(\d+)", stem)
    key = []
    for part in parts:
        if part.isdigit():
            key.append((1, int(part)))
        else:
            key.append((0, part.casefold()))
    return tuple(key)


def _sort_key_for_path(p: Path, sort_kind: str) -> tuple:
    stem = p.stem
    return (_natural_key(stem), stem) if sort_kind == "natural" else _alpha_key(stem)


def _sort_key_for_result(stem: str, sort_kind: str) -> tuple:
    return (_natural_key(stem), stem) if sort_kind == "natural" else _alpha_key(stem)


def process_folder(
    input_dir: Path,
    out_dir: Path | None,
    matrix_basename_override: str | None,
    group_by_size: bool,
    fail_on_mixed_sizes: bool,
    allow_threshold: bool,
    edits: EditOptions,
    emit_dims: bool,
    tool_version: str,
    verbose: bool = False,
    pack_kind: str = "row",
    sort_kind: str = "alpha",   # <-- NEW
) -> List[Path]:
    if not input_dir.exists() or not input_dir.is_dir():
        raise Bmp2CError(f"Not a folder: {input_dir}")

    # order .bmp files
    bmp_paths = sorted(
        [p for p in input_dir.glob("*.bmp") if p.is_file()],
        key=lambda p: _sort_key_for_path(p, sort_kind),
    )
    if not bmp_paths:
        raise Bmp2CError("No .bmp files found")

    results: List[ImageResult] = []
    for p in bmp_paths:
        res = process_single_image(
            input_path=p,
            out_dir=out_dir or input_dir,
            symbol_override=None,
            emit_dims=emit_dims,
            allow_threshold=allow_threshold,
            edits=edits,
            tool_version=tool_version,
            verbose=verbose,
            pack_kind=pack_kind,
        )
        results.append(res)

    results_sorted = sorted(
        results,
        key=lambda r: _sort_key_for_result(r.source_path.stem, sort_kind),
    )

    size_map: Dict[Tuple[int, int], List[ImageResult]] = {}
    for r in results_sorted:
        size_map.setdefault((r.width, r.height), []).append(r)

    if len(size_map) > 1 and fail_on_mixed_sizes:
        raise Bmp2CError(
            "Mixed image sizes after edits; pass --group-by-size to emit separate matrices."
        )

    base_raw = matrix_basename_override or input_dir.name
    base = sanitize_symbol(base_raw)

    written: List[Path] = []
    if group_by_size and len(size_map) > 1:
        for (w, h), group in sorted(size_map.items(), key=lambda it: (it[0][0], it[0][1])):
            suffix = f"_{w}x{h}"
            fname_base = f"{base}{suffix}"
            content = generate_c_matrix(fname_base, group, emit_dims, tool_version, pack_kind=pack_kind)
            out_path = (out_dir or input_dir) / f"{fname_base}_Matrix.c"
            write_text(out_path, content)
            if verbose:
                print(f"Wrote {out_path} (group {w}x{h}, {len(group)} images)")
            written.append(out_path)
    else:
        (w, h), group = next(iter(size_map.items()))
        fname_base = base
        content = generate_c_matrix(fname_base, group, emit_dims, tool_version, pack_kind=pack_kind)
        out_path = (out_dir or input_dir) / f"{fname_base}_Matrix.c"
        write_text(out_path, content)
        if verbose:
            print(f"Wrote {out_path} (matrix {w}x{h}, {len(group)} images)")
        written.append(out_path)

    return written
