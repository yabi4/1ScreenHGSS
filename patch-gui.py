"""1ScreenHGSS - a one-window patcher.

Drop a ROM on the window or click to choose one, pick a colour theme, press
Patch. Replaces patch-rom.bat for people who would rather not meet a console.

It calls onescreen.rom.patch directly rather than shelling out to patch.py:
that function takes bytes and returns bytes and already routes its progress
through a `log` callback, so there is nothing to parse and nothing to quote.
"""

import pathlib
import queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog, ttk

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))


def asset(name):
    """Find a bundled file, whether running from source or from the .exe.

    PyInstaller unpacks --add-data into a temporary tree and points sys._MEIPASS
    at it; from source the same names sit beside this script.
    """
    base = pathlib.Path(getattr(sys, "_MEIPASS", pathlib.Path(__file__).resolve().parent))
    return base / "assets" / name

from onescreen import __version__, themes  # noqa: E402
from onescreen import rom as onescreen_rom  # noqa: E402

# Drag-and-drop needs a third-party package. It is bundled in the built .exe;
# running from source without it simply loses the drop target, not the app.
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
except ImportError:                             # noqa: BLE001
    DND_FILES = TkinterDnD = None

# A real HGSS dump is 128 MiB. Anything wildly off is not worth handing to ndspy,
# which pads short files with zeros and "identifies" them quite happily.
MIN_ROM_BYTES = 8 * 1024 * 1024
GAME_CODE_AT = 0x0C
SUPPORTED_PREFIXES = ("IPG", "IPK")


def inspect(path: pathlib.Path):
    """Return (problem, game_code); problem is None when the file looks patchable.

    Deliberately done here rather than left to ndspy: it validates almost
    nothing, so a text file reaches it and comes back as a raw struct error.
    """
    if not path.is_file():
        return "That file does not exist.", None
    size = path.stat().st_size
    if size < MIN_ROM_BYTES:
        return (f"That file is only {size:,} bytes. A HeartGold or SoulSilver "
                "dump is about 128 MB."), None
    try:
        with path.open("rb") as fh:
            fh.seek(GAME_CODE_AT)
            code = fh.read(4).decode("ascii", "replace")
    except OSError as exc:
        return f"Could not read that file: {exc}", None
    if not code.startswith(SUPPORTED_PREFIXES):
        return (f"That is not HeartGold or SoulSilver - its game code is "
                f"{code!r}. This patch only works on HGSS."), None
    return None, code


class App:
    def __init__(self, root):
        self.root = root
        self.rom = None
        self.busy = False
        self.messages = queue.Queue()
        root.title(f"1ScreenHGSS {__version__}")
        root.resizable(False, False)
        self.set_icon(root)

        frame = ttk.Frame(root, padding=12)
        frame.grid(sticky="nsew")

        self.drop = tk.Label(
            frame, text="Choose a rom to patch\nor drag it here",
            relief="solid", borderwidth=1, width=34, height=4,
            cursor="hand2", justify="center")
        self.drop.grid(row=0, column=0, pady=(0, 12), ipadx=4, ipady=8)
        self.drop.bind("<Button-1>", lambda _e: self.browse())
        # Registering fails if the root was not built by TkinterDnD, or if its
        # Tcl package did not load. Losing the drop target is a small thing;
        # failing to open the window over it is not.
        if TkinterDnD is not None:
            try:
                self.drop.drop_target_register(DND_FILES)
                self.drop.dnd_bind("<<Drop>>", self.on_drop)
            except (tk.TclError, AttributeError):
                pass

        ttk.Label(frame, text="Theme selection").grid(row=1, column=0, sticky="w")
        self.theme = tk.StringVar(value=themes.DEFAULT_THEME)
        self.theme_touched = False
        for i, key in enumerate(("classic", "soulsilver", "heartgold")):
            ttk.Radiobutton(frame, text=themes.THEMES[key]["label"],
                            value=key, variable=self.theme,
                            command=self.theme_chosen).grid(
                row=2 + i, column=0, sticky="w", padx=(8, 0))

        # Off by default: NPC lists the patch does not draw itself use the
        # game's own top-screen list. On, they swap to the touch screen as
        # earlier versions did.
        self.touch_lists = tk.BooleanVar(value=False)
        ttk.Checkbutton(frame, text="Old-style NPC lists (swap screens)",
                        variable=self.touch_lists).grid(
            row=5, column=0, sticky="w", pady=(8, 0))

        self.button = ttk.Button(frame, text="Patch", command=self.start)
        self.button.grid(row=6, column=0, pady=(12, 4))

        self.status = ttk.Label(frame, text="No ROM chosen.", wraplength=250,
                                justify="center")
        self.status.grid(row=7, column=0)
        self.bar = ttk.Progressbar(frame, mode="indeterminate", length=250)

        self.root.after(80, self.drain)

    @staticmethod
    def set_icon(root):
        """Replace Tk's default feather with the Poke Ball.

        Tries the .ico first, which is what Windows wants for the title bar and
        the taskbar; falls back to the PNG elsewhere. A missing or unreadable
        icon is not worth failing to start over.
        """
        ico = asset("1screenhgss.ico")
        try:
            if ico.is_file():
                root.iconbitmap(default=str(ico))
                return
        except tk.TclError:
            pass
        png = asset("1screenhgss.png")
        try:
            if png.is_file():
                root._icon = tk.PhotoImage(file=str(png))
                root.iconphoto(True, root._icon)
        except tk.TclError:
            pass

    # --- choosing a ROM ---------------------------------------------------
    def browse(self):
        if self.busy:
            return
        name = filedialog.askopenfilename(
            title="Choose a HeartGold or SoulSilver ROM",
            filetypes=[("Nintendo DS ROM", "*.nds"), ("All files", "*.*")])
        if name:
            self.choose(pathlib.Path(name))

    def on_drop(self, event):
        if self.busy:
            return
        # Paths arrive brace-wrapped when they contain spaces.
        raw = event.data.strip()
        if raw.startswith("{") and raw.endswith("}"):
            raw = raw[1:-1]
        self.choose(pathlib.Path(raw))

    def theme_chosen(self):
        self.theme_touched = True

    def choose(self, path):
        problem, code = inspect(path)
        if problem:
            self.rom = None
            self.drop.config(text="Choose a rom to patch\nor drag it here")
            self.say(problem)
            return
        self.rom = path
        self.drop.config(text=path.name)
        # Follow the game unless a theme was picked by hand, so choosing one and
        # then browsing for a ROM does not silently undo the choice.
        if self.theme_touched:
            self.say("Ready to patch.")
        else:
            suggested = themes.for_game_code(code)
            self.theme.set(suggested)
            self.say(f"Ready to patch - {themes.THEMES[suggested]['label']} theme.")

    # --- patching ---------------------------------------------------------
    def start(self):
        if self.busy:
            return
        if self.rom is None:
            self.say("Choose a ROM first.")
            return
        out = self.rom.with_name(self.rom.stem + "-1screen.nds")
        if out.resolve() == self.rom.resolve():
            self.say("That name is already taken by the source ROM.")
            return
        self.busy = True
        self.button.state(["disabled"])
        self.bar.grid(row=8, column=0, pady=(8, 0))
        self.bar.start(12)
        self.say("Patching...")
        threading.Thread(target=self.work,
                         args=(self.rom, out, self.theme.get(),
                               self.touch_lists.get()),
                         daemon=True).start()

    def work(self, src, dst, theme, touch_lists=False):
        try:
            data = src.read_bytes()
            out = onescreen_rom.patch(data, log=lambda *_a: None, theme=theme,
                                      touch_lists=touch_lists)
            dst.write_bytes(out)
        except BaseException as exc:            # noqa: BLE001
            # BaseException on purpose: rom.patch raises SystemExit for a ROM it
            # does not recognise, and `except Exception` would let that kill this
            # thread silently.
            self.messages.put(("error", str(exc) or exc.__class__.__name__))
        else:
            self.messages.put(("done", dst.name))

    def drain(self):
        try:
            while True:
                kind, text = self.messages.get_nowait()
                self.busy = False
                self.bar.stop()
                self.bar.grid_remove()
                self.button.state(["!disabled"])
                if kind == "done":
                    self.say(f"Done. Wrote {text}")
                else:
                    self.say(text)
        except queue.Empty:
            pass
        self.root.after(80, self.drain)

    def say(self, text):
        self.status.config(text=text)


def make_root():
    """A drop-capable root when the tkdnd library loads, a plain one otherwise.

    tkinterdnd2 can import fine and still fail here: its compiled library is
    built for Tcl 8, so under Tk 9 loading it raises. `TkinterDnD.Tk()` would
    then have already made its window and take the app down with it; loading
    the library into an ordinary root instead - all `TkinterDnD.Tk` adds, the
    drop methods being on every widget from import - costs only the drop
    target, which App already treats as optional.
    """
    root = tk.Tk()
    if TkinterDnD is not None:
        try:
            root.TkdndVersion = TkinterDnD._require(root)
        except (RuntimeError, tk.TclError):
            pass
    return root


def main():
    root = make_root()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
