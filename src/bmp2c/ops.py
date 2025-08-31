from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple


BitGrid = List[List[int]]  # rows of 0/1


@dataclass(frozen=True)
class EditOptions:
    invert: bool = False
    flip_h: bool = False
    flip_v: bool = False
    rotate: int | None = None  # one of {90, 180, 270} (clockwise)
    trim: bool = False
    pad_left: int = 0
    pad_right: int = 0
    pad_top: int = 0
    pad_bottom: int = 0
    draws: Tuple[Tuple[int, int, str], ...] = ()  # (x, y, "set"|"clear")


def _dims(bits: BitGrid) -> tuple[int, int]:
    h = len(bits)
    w = len(bits[0]) if h > 0 else 0
    return w, h


def op_invert(bits: BitGrid) -> BitGrid:
    return [[1 - px for px in row] for row in bits]


def op_flip_h(bits: BitGrid) -> BitGrid:
    return [list(reversed(row)) for row in bits]


def op_flip_v(bits: BitGrid) -> BitGrid:
    return list(reversed(bits))


def op_rotate(bits: BitGrid, angle: int) -> BitGrid:
    """
    Clockwise rotation by 90/180/270.
    """
    if angle not in (90, 180, 270):
        raise ValueError("rotate must be one of 90, 180, 270")

    w, h = _dims(bits)
    if w == 0 or h == 0:
        return bits

    if angle == 180:
        return op_flip_v(op_flip_h(bits))

    if angle == 90:
        # (x, y) -> (y, new_h-1 - x), new_w = h, new_h = w
        new_w, new_h = h, w
        out = [[0 for _ in range(new_w)] for _ in range(new_h)]
        for y in range(h):
            for x in range(w):
                out[x][new_w - 1 - y] = bits[y][x]
        return out

    # 270 clockwise == 90 counterclockwise
    new_w, new_h = h, w
    out = [[0 for _ in range(new_w)] for _ in range(new_h)]
    for y in range(h):
        for x in range(w):
            out[new_h - 1 - x][y] = bits[y][x]
    return out


def op_trim(bits: BitGrid) -> BitGrid:
    """
    Remove rows/cols that are all white (0).
    If no black pixels exist, return original (avoid 0x0 dimensions).
    """
    w, h = _dims(bits)
    if w == 0 or h == 0:
        return bits

    # Find bounding box of black pixels (1)
    min_x, min_y = w, h
    max_x, max_y = -1, -1
    for y in range(h):
        row = bits[y]
        for x in range(w):
            if row[x] == 1:
                if x < min_x:
                    min_x = x
                if x > max_x:
                    max_x = x
                if y < min_y:
                    min_y = y
                if y > max_y:
                    max_y = y

    if max_x < 0:
        # all white — keep as-is
        return bits

    new = [row[min_x : max_x + 1] for row in bits[min_y : max_y + 1]]
    return new


def op_pad(bits: BitGrid, left: int, right: int, top: int, bottom: int) -> BitGrid:
    if left < 0 or right < 0 or top < 0 or bottom < 0:
        raise ValueError("pad values must be >= 0")

    w, h = _dims(bits)
    new_w = w + left + right
    new_h = h + top + bottom
    if new_w < 0 or new_h < 0:
        raise ValueError("invalid pad size")

    row_white = [0] * new_w
    out: BitGrid = [row_white[:] for _ in range(top)]
    for y in range(h):
        out.append(([0] * left) + bits[y][:] + ([0] * right))
    out.extend([row_white[:] for _ in range(bottom)])
    return out


def op_draw(bits: BitGrid, draws: Tuple[Tuple[int, int, str], ...]) -> BitGrid:
    """
    Apply draws in order. Each draw is (x, y, "set"|"clear").
    Out-of-bounds draws raise a ValueError (clear feedback).
    """
    w, h = _dims(bits)
    out = [row[:] for row in bits]
    for (x, y, action) in draws:
        if not (0 <= x < w and 0 <= y < h):
            raise ValueError(f"--draw out of bounds: ({x},{y}) for size {w}x{h}")
        if action == "set":
            out[y][x] = 1
        elif action == "clear":
            out[y][x] = 0
        else:
            raise ValueError(f"invalid draw action: {action!r}")
    return out


def apply_edits(bits: BitGrid, opts: EditOptions) -> BitGrid:
    """
    Deterministic edit order (before packing):
    invert → flip-h → flip-v → rotate → trim → pad → draws
    """
    out = bits
    if opts.invert:
        out = op_invert(out)
    if opts.flip_h:
        out = op_flip_h(out)
    if opts.flip_v:
        out = op_flip_v(out)
    if opts.rotate is not None:
        out = op_rotate(out, opts.rotate)
    if opts.trim:
        out = op_trim(out)
    if any((opts.pad_left, opts.pad_right, opts.pad_top, opts.pad_bottom)):
        out = op_pad(out, opts.pad_left, opts.pad_right, opts.pad_top, opts.pad_bottom)
    if opts.draws:
        out = op_draw(out, opts.draws)
    return out
