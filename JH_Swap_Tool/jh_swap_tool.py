import argparse
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import swapcore as sc

LIGHT = {sc.GREEN: "#2e9e44", sc.AMBER: "#e0a020", sc.GREY: "#a0a0a0"}
LOOK_BY_TEXT = {v: k for k, v in sc.LOOKS.items()}
COCKPIT_BY_TEXT = {v: k for k, v in sc.COCKPITS.items()}
COLUMNS = 3

# UI only: the JH launcher's look - campaign paper colours, the PWCG button (art/button.png), the logo's black plate for
# Apply (art/plate.png), bold serif lettering
PAPER, PAPER_DK, INK, FAINT, RED = "#e6dcc2", "#d8cba9", "#24180c", "#5a4630", "#8a1c10"


def art_dir():
    for d in (Path(__file__).resolve().parent, Path(getattr(sys, "_MEIPASS", "."))):
        if (d / "art" / "button.png").is_file():
            return d / "art"
    return None


def pwcg_style(root):
    st = ttk.Style(root)
    st.theme_use("clam")
    root.configure(bg=PAPER)
    base = ("Georgia", 10, "bold")
    st.configure(".", background=PAPER, foreground=INK, font=base, fieldbackground="#efe6cf")
    st.configure("TFrame", background=PAPER)
    st.configure("TLabel", background=PAPER, foreground=INK)
    st.configure("TEntry", fieldbackground="#efe6cf", foreground=INK, bordercolor="#a89670", lightcolor="#a89670",
                 darkcolor="#a89670")
    st.configure("TCombobox", fieldbackground="#efe6cf", foreground=INK, arrowcolor=INK, bordercolor="#a89670")
    st.map("TCombobox", fieldbackground=[("readonly", "#efe6cf"), ("disabled", PAPER_DK)])
    st.configure("Horizontal.TProgressbar", background="#2f5a22", troughcolor=PAPER_DK, bordercolor="#a89670")
    d = art_dir()
    if not d:
        return
    root._jh_imgs = imgs = {k: tk.PhotoImage(file=str(d / f"{k}.png")) for k in ("button", "plate")}
    st.element_create("Pwcg.button", "image", imgs["button"], border=(14, 6), sticky="nsew")
    st.layout("TButton", [("Pwcg.button", {"sticky": "nsew", "children": [
        ("Button.padding", {"sticky": "nsew", "children": [("Button.label", {"sticky": "nsew"})]})]})])
    st.configure("TButton", padding=(14, 6), foreground=INK, font=base, background=PAPER)
    st.map("TButton", foreground=[("disabled", "#8c8070"), ("active", RED)])
    st.element_create("Plate.button", "image", imgs["plate"], border=(17, 8), sticky="nsew")
    st.layout("Plate.TButton", [("Plate.button", {"sticky": "nsew", "children": [
        ("Button.padding", {"sticky": "nsew", "children": [("Button.label", {"sticky": "nsew"})]})]})])
    st.configure("Plate.TButton", padding=(26, 8), foreground="#f3ece0", font=("Georgia", 12, "bold"), background=PAPER)
    st.map("Plate.TButton", foreground=[("disabled", "#6e655a"), ("active", "#ffb060")])


class Card:
    def __init__(self, app, parent, slot, aircraft):
        self.app, self.slot = app, slot
        self.frame = ttk.Frame(parent, padding=6, relief="groove", borderwidth=2)
        self.light = tk.Canvas(self.frame, width=18, height=18, highlightthickness=0)
        self.dot = self.light.create_oval(2, 2, 16, 16, fill=LIGHT[sc.GREY], outline="#606060")
        self.light.grid(row=0, column=0, rowspan=2, sticky="n", padx=(0, 6))
        ttk.Label(self.frame, text=f"{slot}  ->  {aircraft}", font=("Georgia", 11, "bold")).grid(
            row=0, column=1, columnspan=2, sticky="w")
        self.source = ttk.Label(self.frame, text="", foreground=FAINT)
        self.source.grid(row=1, column=1, columnspan=2, sticky="w")
        self.status = ttk.Label(self.frame, text="", foreground=FAINT)
        self.status.grid(row=2, column=1, columnspan=2, sticky="w")
        row = ttk.Frame(self.frame)
        row.grid(row=3, column=1, columnspan=2, sticky="w", pady=(4, 0))
        self.look = ttk.Combobox(row, state="readonly", width=18)
        self.look.pack(side="left")
        ttk.Label(row, text="Cockpit").pack(side="left", padx=(10, 4))
        self.cockpit = ttk.Combobox(row, state="readonly", width=8)
        self.cockpit.pack(side="left")
        self.look.bind("<<ComboboxSelected>>", self.changed)
        self.cockpit.bind("<<ComboboxSelected>>", self.changed)

    def changed(self, _event=None):
        self.app.selection[self.slot] = {"source": LOOK_BY_TEXT[self.look.get()],
                                         "cockpit": COCKPIT_BY_TEXT[self.cockpit.get()]}
        self.app.save()
        self.app.update_cards()

    def show(self, sources, chosen, manifest):
        avail = sources.avail[self.slot]
        looks = [sc.OFF, sc.J1946] + ([sc.WT] if avail[sc.WT] else [])
        self.look["values"] = [sc.LOOKS[k] for k in looks]
        self.look.set(sc.LOOKS[chosen["source"]])
        # Aces cockpits are fitted to the WT airframes: offered only with the WT look (a WT plane script on a 1946
        # airframe is not allowed)
        cps = [sc.J1946] + ([sc.ACES] if avail[sc.ACES] and chosen["source"] == sc.WT else [])
        self.cockpit["values"] = [sc.COCKPITS[k] for k in cps]
        self.cockpit.set(sc.COCKPITS[chosen["cockpit"]])
        self.cockpit.configure(state="disabled" if chosen["source"] == sc.OFF else "readonly")
        if chosen["source"] == sc.OFF:
            text = "Source: stock host aircraft"
        else:
            if chosen["source"] == sc.WT:
                ver = sources.wt_manifest.get("wt_version_install") or "?"
                text = f"Source: WT asset pack (WT {ver})"
            else:
                text = "Source: JH 1946 core"
            if chosen["cockpit"] == sc.ACES:
                text += f" + {sources.aces.name.replace(sc.ACES_PREFIX, 'Aces').strip()} cockpit"
            else:
                text += " + 1946 cockpit"
        self.source.configure(text=text)
        colour, status = sc.slot_status(self.slot, chosen, manifest, sources)
        self.light.itemconfigure(self.dot, fill=LIGHT[colour])
        self.status.configure(text=status)


class App:
    def __init__(self, root, settings_file=None):
        self.root = root
        self.settings_file = settings_file
        self.cfg = sc.load_settings(settings_file)
        self.slots = sc.load_slots()
        self.sources = None
        self.manifest = None
        self.busy = False
        self.selection = self.cfg.get("selection") or sc.preset_pure(self.slots)
        root.title("JH Swap Tool - Jungle Hawks 2.5")

        self.mods = tk.StringVar(value=self.cfg.get("mods", ""))
        self.core = tk.StringVar(value=self.cfg.get("core", ""))
        self.wt = tk.StringVar(value=self.cfg.get("wt", ""))
        self.aces = tk.StringVar(value=self.cfg.get("aces", ""))
        self.margin = tk.StringVar(value=str(self.cfg.get("margin_gb", sc.DEFAULT_MARGIN_GB)))
        if not self.mods.get():
            game = sc.find_game()
            if game:
                self.mods.set(str(game / "MODS"))

        top = ttk.Frame(root, padding=8)
        top.pack(fill="x")
        rows = [("MODS folder", self.mods, "Detect"),
                ("1946 core", self.core, None),
                ("WT asset pack", self.wt, None),
                ("Aces cockpits", self.aces, None)]
        for r, (label, var, extra) in enumerate(rows):
            ttk.Label(top, text=label).grid(row=r, column=0, sticky="w", padx=(0, 6))
            ttk.Entry(top, textvariable=var, width=100).grid(row=r, column=1, sticky="we")
            ttk.Button(top, text="Browse...", command=lambda v=var: self.browse(v)).grid(row=r, column=2, padx=4)
            if extra:
                ttk.Button(top, text=extra, command=self.detect).grid(row=r, column=3)
        ttk.Label(top, text="Empty source field = default folder in MODS.", foreground=FAINT).grid(
            row=4, column=1, sticky="w")
        m = ttk.Frame(top)
        m.grid(row=4, column=2, columnspan=2, sticky="e")
        ttk.Label(m, text="Keep free (GB)").pack(side="left")
        ttk.Entry(m, textvariable=self.margin, width=5).pack(side="left", padx=4)
        top.columnconfigure(1, weight=1)

        bar = ttk.Frame(root, padding=(8, 0))
        bar.pack(fill="x")
        ttk.Label(bar, text="Presets:").pack(side="left")
        ttk.Button(bar, text="Pure 1946", command=self.pure).pack(side="left", padx=4)
        ttk.Button(bar, text="Best available", command=self.best).pack(side="left", padx=4)
        ttk.Button(bar, text="Multiplayer server set...", command=self.server_set).pack(side="left", padx=4)
        ttk.Button(bar, text="Rescan", command=self.refresh).pack(side="right")

        grid = ttk.Frame(root, padding=8)
        grid.pack(fill="both", expand=True)
        self.cards = []
        for i, (slot, aircraft) in enumerate(self.slots):
            card = Card(self, grid, slot, aircraft)
            card.frame.grid(row=i // COLUMNS, column=i % COLUMNS, sticky="nsew", padx=3, pady=3)
            self.cards.append(card)
        for c in range(COLUMNS):
            grid.columnconfigure(c, weight=1)

        bottom = ttk.Frame(root, padding=8)
        bottom.pack(fill="x")
        self.apply_btn = ttk.Button(bottom, text="APPLY", command=self.apply, style="Plate.TButton")
        self.apply_btn.pack(side="right")
        self.rollback_btn = ttk.Button(bottom, text="Roll back", command=self.rollback)
        self.rollback_btn.pack(side="right", padx=6)
        self.progress = ttk.Progressbar(bottom, length=200, mode="determinate")
        self.progress.pack(side="right", padx=6)
        self.info = ttk.Label(bottom, text="", wraplength=700, justify="left")
        self.info.pack(side="left", fill="x", expand=True)

        for var in (self.mods, self.core, self.wt, self.aces):
            var.trace_add("write", lambda *_a: self.save())
        self.refresh()

    def browse(self, var):
        path = filedialog.askdirectory(initialdir=var.get() or self.mods.get() or None)
        if path:
            var.set(str(Path(path)))
            self.refresh()

    def detect(self):
        game = sc.find_game()
        if not game:
            messagebox.showwarning("JH Swap Tool", "IL-2 Great Battles (Steam app 307960) not found. "
                                                   "Set the MODS folder manually.")
            return
        self.mods.set(str(game / "MODS"))
        self.refresh()

    def margin_bytes(self):
        try:
            return float(self.margin.get()) * sc.GB
        except ValueError:
            return sc.DEFAULT_MARGIN_GB * sc.GB

    def save(self):
        try:
            margin = float(self.margin.get())
        except ValueError:
            margin = sc.DEFAULT_MARGIN_GB
        sc.save_settings({"mods": self.mods.get(), "core": self.core.get(), "wt": self.wt.get(),
                          "aces": self.aces.get(), "margin_gb": margin, "selection": self.selection},
                         self.settings_file)

    def source_paths(self):
        mods = Path(self.mods.get()) if self.mods.get() else None
        core, wt, aces = sc.default_sources(mods) if mods else (None, None, None)
        return (Path(self.core.get()) if self.core.get() else core,
                Path(self.wt.get()) if self.wt.get() else wt,
                Path(self.aces.get()) if self.aces.get() else aces)

    def refresh(self):
        if self.busy:
            return
        self.root.configure(cursor="watch")
        self.root.update_idletasks()
        try:
            self.sources = sc.Sources(self.slots, *self.source_paths())
            self.manifest = sc.read_active_manifest(self.mods.get()) if self.mods.get() else None
            self.selection, _notes = sc.normalize(self.selection, self.slots, self.sources.avail)
            self.update_cards()
            s = self.sources
            self.set_info(f"Core: {s.core if s.core_files else 'not found'}  |  "
                          f"WT pack: {s.wt or 'not found'}  |  Aces: {s.aces or 'not found'}")
        finally:
            self.root.configure(cursor="")

    def update_cards(self):
        for card in self.cards:
            card.show(self.sources, self.selection[card.slot], self.manifest)

    def set_info(self, text):
        self.info.configure(text=text)

    def set_selection(self, sel, notes=()):
        self.selection = sel
        self.save()
        self.update_cards()
        if notes:
            messagebox.showinfo("JH Swap Tool", "\n".join(notes))

    def pure(self):
        self.set_selection(sc.preset_pure(self.slots))

    def best(self):
        self.set_selection(sc.preset_best(self.slots, self.sources.avail))

    def server_set(self):
        path = filedialog.askopenfilename(filetypes=[("Swap manifest", "*.json"), ("All files", "*.*")])
        if not path:
            return
        try:
            sel, notes = sc.preset_from_file(path, self.slots, self.sources.avail)
        except (OSError, ValueError, AttributeError) as e:
            messagebox.showerror("JH Swap Tool", f"Cannot read {path}:\n{e}")
            return
        self.set_selection(sel, notes)

    def set_busy(self, busy):
        self.busy = busy
        state = "disabled" if busy else "normal"
        self.apply_btn.configure(state=state)
        self.rollback_btn.configure(state=state)

    def apply(self):
        mods = self.mods.get()
        if not mods or not Path(mods).is_dir():
            messagebox.showerror("JH Swap Tool", "Set a valid MODS folder first.")
            return
        self.refresh()
        selection = dict(self.selection)
        sources, margin = self.sources, self.margin_bytes()
        state = {"done": 0, "total": 0, "result": None, "error": None}

        def progress(done, total):
            state["done"], state["total"] = done, total

        def work():
            try:
                state["result"] = sc.apply(sources, selection, mods, margin=margin, progress=progress)
            except (sc.SwapError, OSError) as e:
                state["error"] = str(e)

        self.set_busy(True)
        self.set_info("Building active folder...")
        thread = threading.Thread(target=work, daemon=True)
        thread.start()
        self.poll(thread, state)

    def poll(self, thread, state):
        if state["total"]:
            self.progress.configure(maximum=state["total"], value=state["done"])
        if thread.is_alive():
            self.root.after(200, self.poll, thread, state)
            return
        self.set_busy(False)
        if state["error"]:
            self.set_info("Apply stopped.")
            messagebox.showerror("JH Swap Tool", state["error"])
        else:
            r = state["result"]
            self.set_info(f'Built "{sc.ACTIVE_NAME}": {r["files"]} files, {r["linked"]} hard links, '
                          f'{r["copied"]} copies. Enable it in JSGME.')
        self.refresh()

    def rollback(self):
        mods = self.mods.get()
        try:
            sc.rollback(mods)
        except (sc.SwapError, OSError) as e:
            messagebox.showerror("JH Swap Tool", str(e))
            return
        self.refresh()
        self.set_info("Active folder and backup swapped. Press Roll back again to undo.")


def dpi_aware():
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--settings", help="settings.json path (default %%APPDATA%%\\JH Swap Tool)")
    ap.add_argument("--preview", help="save a PNG of the window and exit")
    args = ap.parse_args(argv)
    dpi_aware()
    root = tk.Tk()
    pwcg_style(root)
    App(root, args.settings)
    if args.preview:
        def grab():
            from PIL import ImageGrab
            root.update()
            x, y = root.winfo_rootx(), root.winfo_rooty()
            w, h = root.winfo_width(), root.winfo_height()
            ImageGrab.grab(bbox=(x, y, x + w, y + h), all_screens=True).save(args.preview)
            root.destroy()
        root.lift()
        root.attributes("-topmost", True)
        root.after(1200, grab)
    root.mainloop()


if __name__ == "__main__":
    sys.exit(main())
