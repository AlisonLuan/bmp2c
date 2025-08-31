from __future__ import annotations

import io
import inspect
import tempfile
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Optional, Tuple, List

from PIL import Image, ImageTk

# --- robust imports for dev, frozen, or -m ---
try:
    # when frozen or run as a script under PyInstaller
    from bmp2c import __version__
    from bmp2c.core import Bmp2CError, process_folder, process_single_image
    from bmp2c.ops import EditOptions
except Exception:  # running as a package (python -m bmp2c.gui)
    from . import __version__
    from .core import Bmp2CError, process_folder, process_single_image
    from .ops import EditOptions


def _parse_draws_multiline(s: str) -> Tuple[Tuple[int, int, str], ...]:
    out = []
    for raw in s.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            xs, ys, action = [p.strip() for p in line.split(",", 2)]
            x = int(xs)
            y = int(ys)
            action_l = action.lower()
            if action_l not in {"set", "clear"}:
                raise ValueError("action must be set|clear")
        except Exception as exc:  # noqa: BLE001
            raise Bmp2CError(f"Invalid draw line: {raw!r} ({exc})")
        out.append((x, y, action_l))
    return tuple(out)


class App(ttk.Frame):
    def __init__(self, master: tk.Tk) -> None:
        super().__init__(master, padding=12)
        self.master.title(f"bmp2c GUI — v{__version__}")
        self._build_menu()  # About on the menubar
        self.master.geometry("980x720")
        self.master.minsize(860, 600)

        # Core vars
        self.input_path = tk.StringVar()
        self.out_dir = tk.StringVar()
        self.allow_threshold = tk.BooleanVar(value=False)
        self.emit_dims = tk.BooleanVar(value=False)
        self.verbose = tk.BooleanVar(value=True)
        self.pack_kind = tk.StringVar(value="page")
        self.pack_kind.trace_add("write", lambda *_: self._editor_render())
        self.sort_kind = tk.StringVar(value="alpha")
        self.symbol_override = tk.StringVar(value="")

        # Edit options
        self.opt_invert = tk.BooleanVar(value=False)
        self.opt_fliph = tk.BooleanVar(value=False)
        self.opt_flipv = tk.BooleanVar(value=False)
        self.opt_trim = tk.BooleanVar(value=False)
        self.rotate_val = tk.StringVar(value="none")
        self.pad_left = tk.IntVar(value=0)
        self.pad_right = tk.IntVar(value=0)
        self.pad_top = tk.IntVar(value=0)
        self.pad_bottom = tk.IntVar(value=0)
        self.draws_text = tk.StringVar(value="")  # kept for API; no widget

        # Pixel editor state
        self.use_editor = tk.BooleanVar(value=False)
        self.editor_zoom = tk.IntVar(value=12)
        self.editor_tool = tk.StringVar(value="pen")
        self.editor_w = tk.IntVar(value=24)
        self.editor_h = tk.IntVar(value=24)

        # --- Move tool state ---
        self._move_active = False
        self._move_start_xy: tuple[int, int] | None = None
        self._move_grid_orig: list[list[int]] | None = None

        # Editor/preview images
        self._edit_grid: Optional[List[List[int]]] = None
        self._photo: Optional[ImageTk.PhotoImage] = None
        self._painting = False

        # Logo image refs (prevent GC)
        self._sidebar_logo_tk: Optional[ImageTk.PhotoImage] = None
        self._about_logo_tk: Optional[ImageTk.PhotoImage] = None

        self._build_ui()
        self._load_sidebar_logo()  # try to show logo immediately

    # ---------- Menubar / About ----------
    def _build_menu(self) -> None:
        menubar = tk.Menu(self.master)

        file_menu = tk.Menu(menubar, tearoff=False)
        file_menu.add_command(label="Browse File…", command=self._choose_file)
        file_menu.add_command(label="Browse Folder…", command=self._choose_dir)
        file_menu.add_separator()
        file_menu.add_command(label="Quit", command=self.master.destroy)
        menubar.add_cascade(label="File", menu=file_menu)

        about_menu = tk.Menu(menubar, tearoff=False)
        about_menu.add_command(label="About bmp2c…", command=self._show_about)
        menubar.add_cascade(label="About", menu=about_menu)

        self.master.config(menu=menubar)

    def _logo_candidates(self) -> List[Path]:
        """
        Candidate locations for logo.png.
        1) src/bmp2c/logo.png (packaged)
        2) next to this file
        3) assets/logo.png next to this file
        4) current working directory
        """
        here = Path(__file__).resolve()
        return [
            here.parent / "logo.png",
            here.parent / "assets" / "logo.png",
            Path.cwd() / "logo.png",
        ]

    def _open_logo_image(self) -> Optional[Image.Image]:
        for p in self._logo_candidates():
            try:
                if p.is_file():
                    return Image.open(p).convert("RGBA")
            except Exception:
                continue
        # Also try pkg resource if project installed with logo included
        try:
            from importlib import resources as importlib_resources
            data = importlib_resources.files(__package__).joinpath("logo.png")
            if data.is_file():
                with data.open("rb") as fh:
                    return Image.open(fh).convert("RGBA")
        except Exception:
            pass
        return None

    def _image_to_photo(self, img: Image.Image, max_w: int, max_h: int) -> ImageTk.PhotoImage:
        # Keep aspect ratio, fit within box; fill alpha with white
        img = img.copy()
        img.thumbnail((max_w, max_h), Image.LANCZOS)
        if img.mode == "RGBA":
            bg = Image.new("RGB", img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[-1])
            img = bg
        else:
            img = img.convert("RGB")
        return ImageTk.PhotoImage(img)

    def _load_sidebar_logo(self) -> None:
        """Load logo.png into the sidebar spot; show placeholder if missing."""
        if not hasattr(self, "sidebar_logo_label"):
            return  # UI not built yet
        img = self._open_logo_image()
        if img is not None:
            self._sidebar_logo_tk = self._image_to_photo(img, max_w=250, max_h=170)
            self.sidebar_logo_label.configure(image=self._sidebar_logo_tk, text="")
        else:
            self.sidebar_logo_label.configure(text="logo.png not found", image="")

    def _show_about(self) -> None:
        top = tk.Toplevel(self.master)
        top.title("About bmp2c")
        top.resizable(False, False)
        frm = ttk.Frame(top, padding=12)
        frm.grid(sticky="nsew")
        frm.columnconfigure(1, weight=1)

        # Left: logo
        logo_img = self._open_logo_image()
        if logo_img is not None:
            self._about_logo_tk = self._image_to_photo(logo_img, max_w=120, max_h=120)
            ttk.Label(frm, image=self._about_logo_tk).grid(row=0, column=0, rowspan=2, padx=(0, 12), sticky="n")
        else:
            ttk.Label(frm, text="logo.png\nnot found", width=14, anchor="center", relief="groove").grid(
                row=0, column=0, rowspan=2, padx=(0, 12), sticky="n"
            )

        # Right: text
        txt = (
            f"bmp2c GUI v{__version__}\n\n"
            "Convert 1-bpp BMPs into MISRA-friendly C arrays (and matrices).\n\n"
            "• Packing: Row-major or vertical 8-pixel pages (LSB-first)\n"
            "• GUI default packing: PAGE\n"
            "• Black=1, White=0; top-left origin (L→R, T→B)\n"
            "• Optional fixed threshold 128 for non-1-bpp inputs\n"
            "• Pixel Editor lets you paint and overwrite or save-as the BMP before conversion\n\n"
            "CLI: bmp2c convert|folder    GUI: bmp2c-gui  /  bmp2c gui\n"
            "License: MIT"
        )
        ttk.Label(frm, text=txt, justify="left").grid(row=0, column=1, sticky="w")

        ttk.Button(frm, text="OK", command=top.destroy).grid(row=1, column=1, sticky="e", pady=(12, 0))

        # Center on parent
        top.update_idletasks()
        w, h = top.winfo_width(), top.winfo_height()
        x = self.master.winfo_rootx() + (self.master.winfo_width() - w) // 2
        y = self.master.winfo_rooty() + (self.master.winfo_height() - h) // 2
        top.geometry(f"+{max(0, x)}+{max(0, y)}")

    # ---------------- UI ----------------
    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)

        # Input / Output
        io_box = ttk.LabelFrame(self, text="Input / Output")
        io_box.grid(row=0, column=0, sticky="nsew", pady=(0, 10))
        for c in range(4):
            io_box.columnconfigure(c, weight=1 if c == 1 else 0)

        ttk.Label(io_box, text="Input (file or folder):").grid(row=0, column=0, sticky="w", padx=8, pady=6)
        ent_in = ttk.Entry(io_box, textvariable=self.input_path)
        ent_in.grid(row=0, column=1, sticky="ew", padx=8)
        ttk.Button(io_box, text="Browse File…", command=self._choose_file).grid(row=0, column=2, padx=4)
        ttk.Button(io_box, text="Browse Folder…", command=self._choose_dir).grid(row=0, column=3, padx=4)

        ttk.Label(io_box, text="Output directory:").grid(row=1, column=0, sticky="w", padx=8, pady=6)
        ent_out = ttk.Entry(io_box, textvariable=self.out_dir)
        ent_out.grid(row=1, column=1, sticky="ew", padx=8)
        ttk.Button(io_box, text="Select…", command=self._choose_out_dir).grid(row=1, column=2, padx=4)

        ttk.Label(io_box, text="Symbol (override / editor):").grid(row=2, column=0, sticky="w", padx=8, pady=6)
        ttk.Entry(io_box, textvariable=self.symbol_override).grid(row=2, column=1, sticky="ew", padx=8)

        # Options (grid: core | geo | pad | logo)
        opts = ttk.LabelFrame(self, text="Options")
        opts.grid(row=1, column=0, sticky="nsew", pady=(0, 10))
        for c in range(4):
            opts.columnconfigure(c, weight=1 if c < 3 else 0)

        core = ttk.Frame(opts)
        core.grid(row=0, column=0, sticky="nsew", padx=8, pady=6)
        ttk.Label(core, text="Packing").grid(row=0, column=0, sticky="w")
        ttk.Combobox(core, textvariable=self.pack_kind, values=("row", "page"), state="readonly").grid(row=0, column=1, sticky="ew", padx=(8, 0))
        ttk.Label(core, text="Sort").grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Combobox(core, textvariable=self.sort_kind, values=("alpha", "natural"), state="readonly").grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=(6, 0))
        ttk.Checkbutton(core, text="Allow threshold (128) for non-1bpp", variable=self.allow_threshold).grid(row=2, column=0, columnspan=2, sticky="w", pady=(8, 0))
        ttk.Checkbutton(core, text="Emit width/height macros", variable=self.emit_dims).grid(row=3, column=0, columnspan=2, sticky="w")
        ttk.Checkbutton(core, text="Verbose log", variable=self.verbose).grid(row=4, column=0, columnspan=2, sticky="w")

        geo = ttk.Frame(opts)
        geo.grid(row=0, column=1, sticky="nsew", padx=8, pady=6)
        ttk.Checkbutton(geo, text="Invert", variable=self.opt_invert).grid(row=0, column=0, sticky="w")
        ttk.Checkbutton(geo, text="Flip H", variable=self.opt_fliph).grid(row=1, column=0, sticky="w")
        ttk.Checkbutton(geo, text="Flip V", variable=self.opt_flipv).grid(row=2, column=0, sticky="w")
        ttk.Checkbutton(geo, text="Trim white border", variable=self.opt_trim).grid(row=3, column=0, sticky="w")
        ttk.Label(geo, text="Rotate").grid(row=4, column=0, sticky="w", pady=(6, 0))
        ttk.Combobox(geo, textvariable=self.rotate_val, values=("none", "90", "180", "270"), state="readonly").grid(row=4, column=1, sticky="ew", padx=(8, 0), pady=(6, 0))

        pad = ttk.Frame(opts)
        pad.grid(row=0, column=2, sticky="nsew", padx=8, pady=6)
        ttk.Label(pad, text="Pad L/R/T/B").grid(row=0, column=0, sticky="w")
        s1 = ttk.Spinbox(pad, from_=0, to=999, textvariable=self.pad_left, width=5)
        s2 = ttk.Spinbox(pad, from_=0, to=999, textvariable=self.pad_right, width=5)
        s3 = ttk.Spinbox(pad, from_=0, to=999, textvariable=self.pad_top, width=5)
        s4 = ttk.Spinbox(pad, from_=0, to=999, textvariable=self.pad_bottom, width=5)
        s1.grid(row=1, column=0, sticky="w", pady=2); ttk.Label(pad, text="Left").grid(row=1, column=1, sticky="w", padx=6)
        s2.grid(row=2, column=0, sticky="w", pady=2); ttk.Label(pad, text="Right").grid(row=2, column=1, sticky="w", padx=6)
        s3.grid(row=3, column=0, sticky="w", pady=2); ttk.Label(pad, text="Top").grid(row=3, column=1, sticky="w", padx=6)
        s4.grid(row=4, column=0, sticky="w", pady=2); ttk.Label(pad, text="Bottom").grid(row=4, column=1, sticky="w", padx=6)

        # Column 3: sidebar logo preview area
        sidebar = ttk.Frame(opts)
        sidebar.grid(row=0, column=3, sticky="nsew", padx=(8, 8), pady=6)
        sidebar.configure(borderwidth=1)
        self.sidebar_logo_label = ttk.Label(
            sidebar,
            text="logo here",
            anchor="center",
            relief="solid",
            padding=8
        )
        self.sidebar_logo_label.pack(fill="both", expand=True)

        # Pixel Editor
        ed = ttk.LabelFrame(self, text="Pixel Editor (1-bpp: black=1, white=0)")
        ed.grid(row=2, column=0, sticky="nsew", pady=(0, 10))
        ed.columnconfigure(1, weight=1)
        ed.rowconfigure(2, weight=1)

        bar = ttk.Frame(ed)
        bar.grid(row=0, column=0, columnspan=2, sticky="w", padx=8, pady=6)
        ttk.Button(bar, text="Load to editor (from Input file)", command=self._editor_load_from_file).grid(row=0, column=0, padx=(0,6))
        ttk.Button(bar, text="New image", command=self._editor_new).grid(row=0, column=1, padx=(0,14))
        ttk.Label(bar, text="W").grid(row=0, column=2)
        self._spin_w = ttk.Spinbox(bar, from_=1, to=2048, width=6,
                                   textvariable=self.editor_w,
                                   command=self._apply_editor_size)
        self._spin_w.grid(row=0, column=3, padx=(2, 10))
        ttk.Label(bar, text="H").grid(row=0, column=4)
        self._spin_h = ttk.Spinbox(bar, from_=1, to=2048, width=6,
                                   textvariable=self.editor_h,
                                   command=self._apply_editor_size)
        self._spin_h.grid(row=0, column=5, padx=(2, 14))
        self._spin_w.bind("<Return>", lambda e: self._apply_editor_size())
        self._spin_h.bind("<Return>", lambda e: self._apply_editor_size())
        self._spin_w.bind("<FocusOut>", lambda e: self._apply_editor_size())
        self._spin_h.bind("<FocusOut>", lambda e: self._apply_editor_size())
        ttk.Radiobutton(bar, text="Pen", value="pen", variable=self.editor_tool).grid(row=0, column=6)
        ttk.Radiobutton(bar, text="Eraser", value="eraser", variable=self.editor_tool).grid(row=0, column=7)
        ttk.Radiobutton(bar, text="Toggle", value="toggle", variable=self.editor_tool).grid(row=0, column=8, padx=(0,14))
        ttk.Radiobutton(bar, text="Move", value="move", variable=self.editor_tool).grid(row=0, column=9)  # NEW
        ttk.Label(bar, text="Zoom").grid(row=0, column=10)
        self._spin_zoom = ttk.Spinbox(bar, from_=4, to=40, width=5,
                                      textvariable=self.editor_zoom,
                                      command=self._editor_render)
        self._spin_zoom.grid(row=0, column=11, padx=(4, 6))
        ttk.Checkbutton(bar, text="Use editor content on Run", variable=self.use_editor).grid(row=0, column=12, padx=(10, 0))

        ttk.Label(ed, text="Tip: Click/drag to paint. Right-click erases. Middle-click toggles.").grid(row=1, column=0, columnspan=2, sticky="w", padx=8)

        self.canvas = tk.Canvas(ed, bg="#FFFFFF", highlightthickness=1, relief="sunken")
        self.canvas.grid(row=2, column=0, columnspan=2, sticky="nsew", padx=8, pady=8)
        self.canvas.bind("<ButtonPress-1>", self._canvas_btn1)
        self.canvas.bind("<B1-Motion>", self._canvas_btn1_move)
        self.canvas.bind("<ButtonRelease-1>", self._canvas_btn1_release)
        self.canvas.bind("<ButtonPress-2>", self._canvas_btn2_toggle)
        self.canvas.bind("<ButtonPress-3>", self._canvas_btn3)

        # Actions / log
        actions = ttk.Frame(self)
        actions.grid(row=3, column=0, sticky="ew")
        actions.columnconfigure(0, weight=1)
        self.run_btn = ttk.Button(actions, text="Run", command=self._run_clicked)
        self.run_btn.grid(row=0, column=1, sticky="e", padx=6, pady=(0, 6))
        ttk.Button(actions, text="Quit", command=self.master.destroy).grid(row=0, column=2, sticky="e", padx=6)
        self.progress = ttk.Progressbar(actions, mode="indeterminate")
        self.progress.grid(row=0, column=0, sticky="ew", padx=(0, 8))

        logbox = ttk.LabelFrame(self, text="Log")
        logbox.grid(row=4, column=0, sticky="nsew")
        self.rowconfigure(4, weight=1)
        logbox.rowconfigure(0, weight=1)
        logbox.columnconfigure(0, weight=1)
        self.log = tk.Text(logbox, height=10, wrap="word")
        self.log.grid(row=0, column=0, sticky="nsew")
        yscroll = ttk.Scrollbar(logbox, orient="vertical", command=self.log.yview)
        yscroll.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=yscroll.set)

        self.pack(fill="both", expand=True)

    # ---------- Pixel editor helpers ----------
    def _ensure_editor_grid(self) -> None:
        if self._edit_grid is None:
            w = max(1, int(self.editor_w.get()))
            h = max(1, int(self.editor_h.get()))
            self._edit_grid = [[0 for _ in range(w)] for _ in range(h)]
            self._editor_render()

    def _editor_new(self) -> None:
        w = max(1, int(self.editor_w.get()))
        h = max(1, int(self.editor_h.get()))
        self._edit_grid = [[0 for _ in range(w)] for _ in range(h)]
        self.use_editor.set(True)
        self._append_log(f"Editor: new {w}x{h} blank image")
        self._editor_render()

    def _editor_load_from_file(self) -> None:
        path = self.input_path.get().strip()
        if not path:
            messagebox.showerror("bmp2c", "Choose an input file first.")
            return
        p = Path(path)
        if not p.is_file():
            messagebox.showerror("bmp2c", "Input path is not a file.")
            return
        try:
            img = Image.open(p)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("bmp2c", f"Failed to open image: {e}")
            return

        try:
            grid = self._image_to_bitgrid(img, allow_threshold=self.allow_threshold.get())
        except Bmp2CError as e:
            messagebox.showerror("bmp2c", str(e))
            return

        self._edit_grid = grid
        h = len(grid)
        w = len(grid[0]) if h else 0
        self.editor_w.set(w)
        self.editor_h.set(h)
        self.use_editor.set(True)
        self._append_log(f"Editor: loaded {p.name} as {w}x{h}")
        self._editor_render()

    @staticmethod
    def _image_to_bitgrid(img: Image.Image, allow_threshold: bool) -> List[List[int]]:
        if img.mode == "1":
            w, h = img.size
            px = img.load()
            out = []
            for y in range(h):
                row = []
                for x in range(w):
                    v = px[x, y]
                    row.append(1 if v == 0 else 0)
                out.append(row)
            return out
        if not allow_threshold:
            raise Bmp2CError("Input is not 1-bpp; enable 'Allow threshold (128)' to load into editor.")
        gray = img.convert("L")
        w, h = gray.size
        px = gray.load()
        out = []
        for y in range(h):
            row = []
            for x in range(w):
                row.append(1 if px[x, y] < 128 else 0)
            out.append(row)
        return out

    def _bitgrid_to_photo(self, grid: List[List[int]], zoom: int) -> ImageTk.PhotoImage:
        h = len(grid)
        w = len(grid[0]) if h else 0
        base = Image.new("RGB", (w, h), (255, 255, 255))
        px = base.load()
        for y in range(h):
            row = grid[y]
            for x in range(w):
                if row[x] == 1:
                    px[x, y] = (0, 0, 0)
        if zoom != 1:
            base = base.resize((w * zoom, h * zoom), Image.NEAREST)
        return ImageTk.PhotoImage(base)

    def _editor_render(self, *_args) -> None:
        if self._edit_grid is None:
            self.canvas.delete("all")
            return
        zoom = max(1, int(self.editor_zoom.get()))
        self._photo = self._bitgrid_to_photo(self._edit_grid, zoom)
        self.canvas.configure(width=self._photo.width(), height=self._photo.height(),
                              scrollregion=(0, 0, self._photo.width(), self._photo.height()))
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor="nw", image=self._photo)
        if zoom >= 10 and len(self._edit_grid) <= 128 and len(self._edit_grid[0]) <= 128:
            w = len(self._edit_grid[0]) * zoom
            h = len(self._edit_grid) * zoom
            for x in range(0, w + 1, zoom):
                self.canvas.create_line(x, 0, x, h, fill="#DDDDDD")
            for y in range(0, h + 1, zoom):
                self.canvas.create_line(0, y, w, y, fill="#DDDDDD")

        # --- PAGE GUIDES (Packing = page): 2 screen pixels thick, black ---
        if self.pack_kind.get() == "page":
            grid_h = len(self._edit_grid)
            grid_w = len(self._edit_grid[0]) if grid_h else 0
            if grid_h > 0 and grid_w > 0:
                canvas_w = grid_w * zoom
                guide_thickness = 2  # fixed, screen pixels
                # draw at y = 8, 16, 24, ... (skip 0 and bottom edge)
                for y_cell in range(8, grid_h, 8):
                    y0 = y_cell * zoom
                    # rectangle is crisp and avoids antialiasing issues with thick lines
                    self.canvas.create_rectangle(
                        0, y0, canvas_w, y0 + guide_thickness, outline="", fill="#000000"
                    )

    def _paint_at(self, x: int, y: int, action: str) -> None:
        if self._edit_grid is None:
            return
        h = len(self._edit_grid)
        w = len(self._edit_grid[0]) if h else 0
        if not (0 <= x < w and 0 <= y < h):
            return
        if action == "pen":
            self._edit_grid[y][x] = 1
        elif action == "eraser":
            self._edit_grid[y][x] = 0
        elif action == "toggle":
            self._edit_grid[y][x] = 1 - self._edit_grid[y][x]
        self._editor_render()

    def _pixel_from_event(self, event) -> Tuple[int, int]:
        zoom = max(1, int(self.editor_zoom.get()))
        return event.x // zoom, event.y // zoom

    def _canvas_btn1(self, event) -> None:
        self._ensure_editor_grid()
        x, y = self._pixel_from_event(event)

        if self.editor_tool.get() == "move":
            if self._edit_grid is None:
                return
            # start move: remember starting point and original grid snapshot
            self._move_active = True
            self._move_start_xy = (x, y)
            self._move_grid_orig = [row[:] for row in self._edit_grid]
            return

        # default: paint tools
        self._painting = True
        self._paint_at(x, y, self.editor_tool.get())

    def _canvas_btn1_move(self, event) -> None:
        if self.editor_tool.get() == "move" and self._move_active and self._move_grid_orig is not None:
            x, y = self._pixel_from_event(event)
            x0, y0 = self._move_start_xy or (x, y)
            dx, dy = x - x0, y - y0
            # apply translation relative to the snapshot
            self._edit_grid = self._translate_grid(self._move_grid_orig, dx, dy)
            self._editor_render()
            return

        if not self._painting:
            return
        x, y = self._pixel_from_event(event)
        self._paint_at(x, y, self.editor_tool.get())

    def _canvas_btn1_release(self, _event) -> None:
        if self.editor_tool.get() == "move":
            # commit and clear move state
            self._move_active = False
            self._move_start_xy = None
            self._move_grid_orig = None
            return
        self._painting = False

    def _canvas_btn2_toggle(self, event) -> None:
        self._ensure_editor_grid()
        x, y = self._pixel_from_event(event)
        self._paint_at(x, y, "toggle")

    def _canvas_btn3(self, event) -> None:
        self._ensure_editor_grid()
        x, y = self._pixel_from_event(event)
        self._paint_at(x, y, "eraser")

    # ---------- Generic helpers ----------
    def _choose_file(self) -> None:
        p = filedialog.askopenfilename(
            title="Choose 1-bpp BMP file",
            filetypes=[("BMP images", "*.bmp"), ("All files", "*.*")],
        )
        if p:
            self.input_path.set(p)
            try:
                self.out_dir.set(str(Path(p).parent))  # auto-fill output dir
            except Exception:
                pass
            self._editor_load_from_file()  # auto-load into editor
            self._load_sidebar_logo()      # in case logo dropped next to the file/project

    def _choose_dir(self) -> None:
        p = filedialog.askdirectory(title="Choose folder of BMPs")
        if p:
            self.input_path.set(p)
            try:
                self.out_dir.set(str(Path(p)))  # auto-fill output dir
            except Exception:
                pass
            self._load_sidebar_logo()

    def _choose_out_dir(self) -> None:
        p = filedialog.askdirectory(title="Choose output directory")
        if p:
            self.out_dir.set(p)

    def _append_log(self, text: str) -> None:
        self.log.insert("end", text if text.endswith("\n") else text + "\n")
        self.log.see("end")

    def _disable_ui(self, disabled: bool) -> None:
        state = "disabled" if disabled else "normal"
        for child in self.winfo_children():
            try:
                child.configure(state=state)
            except tk.TclError:
                pass
        self.log.configure(state="normal")
        self.run_btn.configure(state="disabled" if disabled else "normal")

    # ---------- Run ----------
    def _run_clicked(self) -> None:
        path = self.input_path.get().strip()
        target = Path(path) if path else None
        out_dir = Path(self.out_dir.get()) if self.out_dir.get().strip() else None

        rv = self.rotate_val.get()
        rotate: Optional[int] = int(rv) if rv in {"90", "180", "270"} else None

        try:
            draws = _parse_draws_multiline(self.draws_text.get())
        except Bmp2CError as e:
            messagebox.showerror("bmp2c", str(e))
            return

        edits = EditOptions(
            invert=self.opt_invert.get(),
            flip_h=self.opt_fliph.get(),
            flip_v=self.opt_flipv.get(),
            rotate=rotate,
            trim=self.opt_trim.get(),
            pad_left=max(0, int(self.pad_left.get())),
            pad_right=max(0, int(self.pad_right.get())),
            pad_top=max(0, int(self.pad_top.get())),
            pad_bottom=max(0, int(self.pad_bottom.get())),
            draws=draws if not self.use_editor.get() else tuple(),
        )

        args_common = dict(
            out_dir=out_dir,
            emit_dims=self.emit_dims.get(),
            allow_threshold=self.allow_threshold.get(),
            edits=edits,
            tool_version=__version__,
            verbose=self.verbose.get(),
            pack_kind=self.pack_kind.get(),
        )
        sort_kind = self.sort_kind.get()

        def worker():
            buf_out, buf_err = io.StringIO(), io.StringIO()
            try:
                with redirect_stdout(buf_out), redirect_stderr(buf_err):
                    if self.use_editor.get() and self._edit_grid is not None:
                        symbol = self.symbol_override.get().strip() or (
                            (target.stem if (target and target.is_file()) else "EditedImage")
                        )

                        if target and target.is_file():
                            overwrite = messagebox.askyesno(
                                "Overwrite original image?",
                                f"You loaded '{target.name}'.\n\n"
                                "Do you want to OVERWRITE this file with the edited image?\n\n"
                                "Choose 'No' to save the edited image elsewhere."
                            )
                            if overwrite:
                                dest = target
                            else:
                                save_as = filedialog.asksaveasfilename(
                                    title="Save edited image as BMP",
                                    defaultextension=".bmp",
                                    filetypes=[("BMP image", "*.bmp")],
                                    initialdir=str(target.parent),
                                    initialfile=target.name,
                                )
                                if not save_as:
                                    self._append_log("Save canceled; run aborted.")
                                    return
                                dest = Path(save_as)

                            self._save_editor_to_path(dest)
                            self._append_log(f"[editor] Saved edited BMP -> {dest}")

                            if args_common["out_dir"] is None:
                                args_common["out_dir"] = dest.parent

                            process_single_image(
                                input_path=dest,
                                symbol_override=symbol,
                                **args_common,
                            )
                            self.input_path.set(str(dest))
                            return

                        # New image (no original file): keep temp flow
                        tmp_path = None
                        try:
                            tmp_path = self._save_editor_to_temp_bmp()
                            self._append_log(f"[convert/editor] {symbol} from editor ({tmp_path.name})")
                            process_single_image(
                                input_path=tmp_path,
                                symbol_override=symbol,
                                **args_common,
                            )
                        finally:
                            if tmp_path and tmp_path.exists():
                                try:
                                    tmp_path.unlink()
                                except Exception:
                                    pass
                        return

                    if not target:
                        raise Bmp2CError("Please choose an input file or folder, or enable the editor and create a new image.")
                    if target.is_file():
                        self._append_log(f"[convert] {target}")
                        process_single_image(
                            input_path=target,
                            symbol_override=(self.symbol_override.get().strip() or None),
                            **args_common,
                        )
                    elif target.is_dir():
                        self._append_log(f"[folder] {target}")
                        kwargs = dict(
                            input_dir=target,
                            matrix_basename_override=None,
                            group_by_size=True,
                            fail_on_mixed_sizes=False,
                            **args_common,
                        )
                        sig = inspect.signature(process_folder)
                        if "sort_kind" in sig.parameters:
                            kwargs["sort_kind"] = sort_kind
                        else:
                            if sort_kind != "alpha":
                                self._append_log("Note: installed core lacks natural sort; falling back to alpha.")
                        process_folder(**kwargs)
                    else:
                        raise Bmp2CError("Input path is neither a file nor a folder.")
            except Bmp2CError as e:
                self._append_log(str(e))
                messagebox.showerror("bmp2c", str(e))
            except Exception as e:  # noqa: BLE001
                self._append_log(f"Unexpected error: {e!r}")
                messagebox.showerror("bmp2c", f"Unexpected error: {e}")
            finally:
                out_txt = buf_out.getvalue()
                err_txt = buf_err.getvalue()
                if out_txt:
                    self._append_log(out_txt.strip())
                if err_txt:
                    self._append_log(err_txt.strip())
                self.progress.stop()
                self._disable_ui(False)

        self._disable_ui(True)
        self.progress.start(10)
        threading.Thread(target=worker, daemon=True).start()

    # ---------- Editor persistence ----------
    def _save_editor_to_temp_bmp(self) -> Path:
        if self._edit_grid is None:
            raise Bmp2CError("Editor has no image to save.")
        h = len(self._edit_grid)
        w = len(self._edit_grid[0]) if h else 0
        if w == 0 or h == 0:
            raise Bmp2CError("Editor image has zero size.")
        img = Image.new("1", (w, h), 255)
        px = img.load()
        for y in range(h):
            row = self._edit_grid[y]
            for x in range(w):
                if row[x] == 1:
                    px[x, y] = 0
        tmp = tempfile.NamedTemporaryFile(prefix="bmp2c_editor_", suffix=".bmp", delete=False)
        tmp_path = Path(tmp.name)
        tmp.close()
        img.save(tmp_path, format="BMP")
        return tmp_path

    def _save_editor_to_path(self, dest_path: Path) -> None:
        if self._edit_grid is None:
            raise Bmp2CError("Editor has no image to save.")
        h = len(self._edit_grid)
        w = len(self._edit_grid[0]) if h else 0
        if w == 0 or h == 0:
            raise Bmp2CError("Editor image has zero size.")
        img = Image.new("1", (w, h), 255)
        px = img.load()
        for y in range(h):
            row = self._edit_grid[y]
            for x in range(w):
                if row[x] == 1:
                    px[x, y] = 0
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(dest_path, format="BMP")

    def _resize_bitgrid_nn(self, grid: list[list[int]], new_w: int, new_h: int) -> list[list[int]]:
        """
        Resize a BitGrid using nearest-neighbor (pixel stretch).
        grid: [h][w] with values 0/1. Returns new grid [new_h][new_w].
        """
        in_h = len(grid)
        in_w = len(grid[0]) if in_h else 0
        new_w = max(1, int(new_w))
        new_h = max(1, int(new_h))
        if in_w == 0 or in_h == 0:
            return [[0 for _ in range(new_w)] for _ in range(new_h)]

        out: list[list[int]] = []
        # Map each out coord to an in coord using integer math (fast + stable)
        for y_out in range(new_h):
            y_in = min(in_h - 1, (y_out * in_h) // new_h)
            row_out: list[int] = []
            for x_out in range(new_w):
                x_in = min(in_w - 1, (x_out * in_w) // new_w)
                row_out.append(grid[y_in][x_in])
            out.append(row_out)
        return out

    def _apply_editor_size(self) -> None:
        """
        Called when W/H spinboxes change or on Enter/FocusOut.
        If an editor image exists, resize it in-place and re-render.
        """
        try:
            w = max(1, int(self.editor_w.get()))
            h = max(1, int(self.editor_h.get()))
        except Exception:
            return  # ignore partial/invalid edits while typing

        if self._edit_grid is None:
            return  # no image yet; W/H act as defaults for "New image"

        cur_h = len(self._edit_grid)
        cur_w = len(self._edit_grid[0]) if cur_h else 0
        if w == cur_w and h == cur_h:
            return

        self._edit_grid = self._resize_bitgrid_nn(self._edit_grid, w, h)
        self._append_log(f"Editor: resized to {w}x{h} (nearest-neighbor)")
        self._editor_render()

    def _translate_grid(self, grid: list[list[int]], dx: int, dy: int) -> list[list[int]]:
        """
        Translate the bitmap by integer pixels (dx, dy).
        Pixels shifted out are dropped; vacated area becomes white (0).
        Returns a new grid of the same size.
        """
        h = len(grid)
        w = len(grid[0]) if h else 0
        if w == 0 or h == 0 or (dx == 0 and dy == 0):
            return [row[:] for row in grid]

        out = [[0 for _ in range(w)] for _ in range(h)]
        for y in range(h):
            src_y = y - dy
            if 0 <= src_y < h:
                row_out = out[y]
                row_src = grid[src_y]
                for x in range(w):
                    src_x = x - dx
                    if 0 <= src_x < w:
                        row_out[x] = row_src[src_x]
        return out


def main() -> None:
    root = tk.Tk()
    try:
        style = ttk.Style()
        if "vista" in style.theme_names():
            style.theme_use("vista")
        elif "clam" in style.theme_names():
            style.theme_use("clam")
    except Exception:
        pass
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
