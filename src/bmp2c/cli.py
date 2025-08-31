from __future__ import annotations

import argparse
import sys
import unittest
from pathlib import Path
from typing import List, Sequence, Tuple

# --- robust imports for dev, frozen, or -m ---
try:
    # when frozen or run as a script under PyInstaller
    from bmp2c import __version__
    from bmp2c.core import Bmp2CError, process_folder, process_single_image
    from bmp2c.ops import EditOptions
except Exception:  # running as a package (python -m bmp2c.cli)
    from . import __version__
    from .core import Bmp2CError, process_folder, process_single_image
    from .ops import EditOptions


def _parse_draws(values: Sequence[str]) -> Tuple[Tuple[int, int, str], ...]:
    out = []
    for v in values:
        try:
            xy, action = v.rsplit(",", 1)
            xs, ys = xy.split(",", 1)
            x = int(xs.strip())
            y = int(ys.strip())
            action = action.strip().lower()
        except Exception as exc:  # noqa: BLE001
            raise argparse.ArgumentTypeError(f"invalid --draw: {v!r}") from exc
        if action not in {"set", "clear"}:
            raise argparse.ArgumentTypeError(f"invalid draw action: {action!r}")
        out.append((x, y, action))
    return tuple(out)


def _edit_options_from_args(ns: argparse.Namespace) -> EditOptions:
    return EditOptions(
        invert=ns.invert,
        flip_h=ns.flip_h,
        flip_v=ns.flip_v,
        rotate=ns.rotate,
        trim=ns.trim,
        pad_left=ns.pad_left or 0,
        pad_right=ns.pad_right or 0,
        pad_top=ns.pad_top or 0,
        pad_bottom=ns.pad_bottom or 0,
        draws=_parse_draws(ns.draw or []),
    )


def _add_common_edit_flags(p: argparse.ArgumentParser) -> None:
    p.add_argument("--invert", action="store_true", help="invert pixels (black<->white)")
    p.add_argument("--flip-h", action="store_true", help="horizontal flip")
    p.add_argument("--flip-v", action="store_true", help="vertical flip")
    p.add_argument("--rotate", type=int, choices=[90, 180, 270], help="rotate clockwise")
    p.add_argument("--trim", action="store_true", help="trim white rows/cols")
    p.add_argument("--pad-left", type=int, metavar="N", help="pad white left N")
    p.add_argument("--pad-right", type=int, metavar="N", help="pad white right N")
    p.add_argument("--pad-top", type=int, metavar="N", help="pad white top N")
    p.add_argument("--pad-bottom", type=int, metavar="N", help="pad white bottom N")
    p.add_argument(
        "--draw",
        metavar='"x,y,set|clear"',
        action="append",
        help="draw a pixel (may be repeated)",
    )


def _add_common_io_flags(p: argparse.ArgumentParser) -> None:
    p.add_argument("--out-dir", type=Path, help="output directory (defaults next to input)")
    p.add_argument(
        "--allow-threshold",
        action="store_true",
        help="allow non-1bpp BMPs; binarize with fixed threshold=128",
    )
    p.add_argument("--emit-dims", action="store_true", help="emit width/height macros")
    p.add_argument("--verbose", action="store_true", help="verbose logging")
    p.add_argument(
        "--pack",
        choices=["row", "page"],
        default="row",
        help="packing mode: 'row' = row-major LSB-first (default); "
             "'page' = vertical 8px pages LSB-first (SSD1306-style)",
    )
    p.add_argument(
        "--sort",
        choices=["alpha", "natural"],
        default="alpha",
        help="image ordering: 'alpha' (case-insensitive) or 'natural' (numeric-aware)",
    )


def run_selftest() -> int:
    loader = unittest.TestLoader()
    suite = loader.discover(start_dir=str(Path(__file__).parent.parent.parent / "tests"))
    runner = unittest.TextTestRunner(verbosity=2)
    res = runner.run(suite)
    return 0 if res.wasSuccessful() else 1


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="bmp2c",
        description="Convert 1-bpp BMPs into MISRA-friendly C arrays (and matrices).",
    )
    ap.add_argument("--selftest", action="store_true", help="run the internal test suite and exit")
    ap.add_argument("--version", action="version", version=f"bmp2c {__version__}")

    sub = ap.add_subparsers(dest="cmd", required=False)

    # --- NEW: gui subcommand
    sub.add_parser("gui", help="launch the graphical user interface")

    # convert
    p_conv = sub.add_parser("convert", help="convert a single BMP to .c")
    p_conv.add_argument("input", type=Path, metavar="input.bmp")
    p_conv.add_argument("--symbol", type=str, help="override C symbol (default: sanitized stem)")
    _add_common_io_flags(p_conv)
    _add_common_edit_flags(p_conv)

    # folder
    p_fold = sub.add_parser("folder", help="process a folder of BMPs; emit per-file .c and a matrix")
    p_fold.add_argument("dir", type=Path, metavar="dir")
    p_fold.add_argument(
        "--matrix-basename",
        type=str,
        help="basename for matrix C file (default: sanitized folder name)",
    )
    g = p_fold.add_mutually_exclusive_group()
    g.add_argument(
        "--group-by-size",
        action="store_true",
        help="emit separate matrices per WxH (default behavior)",
    )
    g.add_argument(
        "--fail-on-mixed-sizes",
        action="store_true",
        help="fail if sizes differ after edits",
    )
    _add_common_io_flags(p_fold)
    _add_common_edit_flags(p_fold)

    return ap


def main(argv: List[str] | None = None) -> None:
    import sys as _sys
    argv = list(_sys.argv[1:] if argv is None else argv)
    ap = build_parser()
    ns = ap.parse_args(argv)

    if ns.cmd == "gui":
        # lazy import to keep CLI startup fast
        from .gui import main as gui_main
        gui_main()
        return

    if ns.selftest and ns.cmd is None:
        _sys.exit(run_selftest())

    if ns.cmd == "convert":
        edits = _edit_options_from_args(ns)
        try:
            process_single_image(
                input_path=ns.input,
                out_dir=ns.out_dir,
                symbol_override=ns.symbol,
                emit_dims=ns.emit_dims,
                allow_threshold=ns.allow_threshold,
                edits=edits,
                tool_version=__version__,
                verbose=ns.verbose,
                pack_kind=ns.pack,
            )
        except Bmp2CError as e:
            print(str(e), file=_sys.stderr)
            _sys.exit(2)
        return

    if ns.cmd == "folder":
        edits = _edit_options_from_args(ns)
        try:
            process_folder(
                input_dir=ns.dir,
                out_dir=ns.out_dir,
                matrix_basename_override=ns.matrix_basename,
                group_by_size=ns.group_by_size or not ns.fail_on_mixed_sizes,
                fail_on_mixed_sizes=ns.fail_on_mixed_sizes,
                allow_threshold=ns.allow_threshold,
                edits=edits,
                emit_dims=ns.emit_dims,
                tool_version=__version__,
                verbose=ns.verbose,
                pack_kind=ns.pack,
                sort_kind=ns.sort,   # <-- NEW
            )
        except Bmp2CError as e:
            print(str(e), file=_sys.stderr)
            _sys.exit(2)
        return

    ap.print_help()
    _sys.exit(1)
