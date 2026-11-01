"""The app's window: a notebook of pages over a back end (backend.py). Stock Tk/ttk only.

All platform behaviour comes from the back end; the platform-only sections are built when the back end lists
them (install_sections, play_sections, extra_pages)."""

import queue
import threading
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

from backend import HG_RENDERER
from backend import DISC2_FIXES, installed_version

# Not exactly "Heavy Gear": the official patchers wait, showing only a black window, while any window
# has that title (they take it for the running game).
TITLE = "Heavy Gear Fixes"
KEEP_RENDERER = "Keep the game's current renderer setting"
# Each plugin under the name the game's Graphics Type list gives it (the name the plugin reports), then what it is.
RENDERER_LABELS = {
    HG_RENDERER: "Direct3D 9 renderer: this project's, high resolution (3dfx_hgd3d9.dll)",
    "3dfxgear.dll": "3Dfx: Glide, needs nGlide or dgVoodoo2 (3dfxgear.dll)",
    "dx5draw.dll": "Direct3D: the original Direct3D 5 renderer (dx5draw.dll)",
    "i76draw.dll": "Software: the engine's own renderer (i76draw.dll)",
}
D3D9_LABEL = RENDERER_LABELS[HG_RENDERER]


def renderer_label(filename):
    return RENDERER_LABELS.get(filename.casefold(), filename)
PAGE_TITLES = {"play": "Play", "fixes": "Fixes", "install": "Install & update", "tools": "Tools"}
GLIDE_HELP = (
    "The 3Dfx renderer (3DFXGEAR.DLL) needs a Glide driver, glide2x.dll. On modern Windows that is a wrapper:\n\n"
    "nGlide (free): download it from zeus-software.com/downloads/nglide and run its installer. It puts "
    "glide2x.dll in C:\\Windows\\SysWOW64, which this app finds by itself. With the borderless fix and 3Dfx "
    "selected, Apply & Play sets nGlide to render at the desktop's resolution in 4:3 (nglide_config.exe's "
    "By desktop and Aspect correction, shared by every game nGlide runs).\n\n"
    "dgVoodoo2: from dege.freeweb.hu, unpack the archive and choose its 3Dfx\\x86\\Glide2x.dll.\n\n"
    "The driver goes into the game folder as glide2x_real.dll, behind this app's particle fix (glide2x.dll), "
    "which draws smoke, dust and fire properly instead of as black squares. Choose 3Dfx in the game's options "
    "afterwards. Run it again after updating the wrapper or this app."
)
NEW_CONTROLS = ("action", "sim", "wasd")
EXISTING_CONTROLS = ("keep existing", "wasd")


# --- styling and shared widgets --------------------------------------------------------------------

def apply_style(root):
    """Theme, spacing and check-box size from the font, so the window reads well at any display scaling.
    Returns the base padding in pixels."""
    style = ttk.Style(root)
    style.theme_use("vista" if "vista" in style.theme_names() else "clam")
    base = tkfont.nametofont("TkDefaultFont")
    line = base.metrics("linespace")
    pad = max(4, line // 3)
    indicator = max(12, line * 3 // 4)
    for name in ("TCheckbutton", "TRadiobutton"):
        style.configure(name, indicatorsize=indicator, indicatormargin=(0, 0, pad, 0), padding=(0, pad // 3))
    style.configure("TButton", padding=(pad, pad // 2))
    style.configure("TNotebook.Tab", padding=(pad * 2, pad // 2))
    heading = base.copy()
    heading.configure(weight="bold")
    root._heading_font = heading            # keep a reference: Tk forgets fonts Python drops
    style.configure("TLabelframe.Label", font=heading)
    style.configure("Heading.TLabel", font=heading)
    style.configure("Good.TLabel", foreground="#1a6b1a")
    style.configure("Bad.TLabel", foreground="#b00020")
    style.configure("Note.TLabel", foreground="#505050")
    return pad


class WrapLabel(ttk.Label):
    """A label whose text wraps to the width it is given, not a fixed number of pixels."""

    def __init__(self, parent, **options):
        options.setdefault("justify", "left")
        super().__init__(parent, **options)
        # A modest first width, so a long line doesn't make the window wide before the first layout.
        self.configure(wraplength=tkfont.nametofont("TkDefaultFont").measure("0") * 60)
        self.bind("<Configure>", lambda event: self.configure(wraplength=max(1, event.width - 2)))


class Tooltip:
    """Text shown in a small pop-up while the pointer is over a widget."""

    def __init__(self, widget, text):
        self.widget, self.text, self.window = widget, text, None
        widget.bind("<Enter>", self.show, add="+")
        widget.bind("<Leave>", self.hide, add="+")
        widget.bind("<Destroy>", self.hide, add="+")

    def show(self, _event=None):
        if self.window:
            return
        self.window = tk.Toplevel(self.widget)
        self.window.wm_overrideredirect(True)
        self.window.wm_geometry(f"+{self.widget.winfo_rootx()}+{self.widget.winfo_rooty() + self.widget.winfo_height()}")
        tk.Label(self.window, text=self.text, justify="left", background="#ffffe0", relief="solid", borderwidth=1,
                 wraplength=tkfont.nametofont("TkDefaultFont").measure("0") * 70, padx=6, pady=4).pack()

    def hide(self, _event=None):
        if self.window:
            self.window.destroy()
            self.window = None


class ScrollPage(ttk.Frame):
    """A page whose content scrolls when it is taller than the window, with a fixed row of action buttons."""

    def __init__(self, parent, pad):
        super().__init__(parent)
        self.actions = ttk.Frame(self, padding=(pad, pad // 2, pad, pad))
        self.actions.pack(side="bottom", fill="x")
        self.canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0, width=1, height=1)
        self.bar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.bar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.content = ttk.Frame(self.canvas, padding=pad)
        self._item = self.canvas.create_window((0, 0), window=self.content, anchor="nw")
        self.content.bind("<Configure>", self._resized)
        self.canvas.bind("<Configure>", self._resized)

    def _resized(self, _event=None):
        if self.canvas.winfo_width() > 1:      # not laid out yet: keep the content at its own width
            self.canvas.itemconfigure(self._item, width=self.canvas.winfo_width())
        self.canvas.configure(scrollregion=(0, 0, 0, self.content.winfo_reqheight()))
        if self.content.winfo_reqheight() > self.canvas.winfo_height() > 1:
            self.bar.pack(side="right", fill="y", before=self.canvas)
        else:
            self.bar.pack_forget()
            self.canvas.yview_moveto(0)

    def scroll(self, event):
        if self.bar.winfo_ismapped():
            self.canvas.yview_scroll(-3 if event.num == 4 or event.delta > 0 else 3, "units")


# --- the window ----------------------------------------------------------------------------------------

class App:
    def __init__(self, root, backend, saved=None):
        self.root = root
        self.backend = backend
        self.pad = apply_style(root)
        root.title(TITLE)
        root.protocol("WM_DELETE_WINDOW", self.close)
        saved = backend.load_settings() if saved is None else saved
        self.vars = {}
        self.fix_vars = {}
        for key, value in backend.initial_choices(saved).items():
            if key == "fixes":
                self.fix_vars = {name: tk.BooleanVar(root, value=on) for name, on in value.items()}
            elif isinstance(value, bool):
                self.vars[key] = tk.BooleanVar(root, value=value)
            else:
                self.vars[key] = tk.StringVar(root, value=value)
        self.header_status = tk.StringVar(root)
        self.status = tk.StringVar(root, value="Ready.")
        self.install_mode = tk.StringVar(root)
        self.requirements = tk.StringVar(root)
        self.renderer_label = tk.StringVar(root)
        self.renderer_files = {}
        self.path_checks = {}           # key -> (note variable, label)
        self.action_buttons = []
        self.busy = False
        self.close_when_done = False
        self.jobs = queue.Queue()
        self._refresh_pending = False

        self._build_header()
        self._build_bottom()
        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill="both", expand=True, padx=self.pad)
        self.pages = {}
        for name in ("play", "fixes", "install", *backend.extra_pages):
            page = ScrollPage(self.notebook, self.pad)
            self.notebook.add(page, text=PAGE_TITLES[name])
            self.pages[name] = page
            getattr(self, f"_build_{name}")(page)
        for sequence in ("<Button-4>", "<Button-5>", "<MouseWheel>"):
            root.bind_all(sequence, lambda event: self.pages[self.current_page()].scroll(event))
        self.vars["location"].trace_add("write", lambda *_: self._schedule_refresh())
        self.refresh()
        self._fit()
        self.show_page("play" if backend.find_game(saved) else "install")

    # --- layout helpers ---------------------------------------------------------------------------
    def _section(self, parent, title):
        frame = ttk.LabelFrame(parent, text=title, padding=self.pad)
        frame.pack(fill="x", pady=(0, self.pad))
        frame.columnconfigure(0, weight=1)
        return frame

    def _note(self, parent, row=None, textvariable=None, text="", style="Note.TLabel", **grid):
        label = WrapLabel(parent, text=text, textvariable=textvariable, style=style)
        if row is None:
            label.pack(fill="x", pady=(0, self.pad))
        else:
            label.grid(row=row, column=0, columnspan=4, sticky="ew", **grid)
        return label

    def _check(self, parent, row, text, variable, command=None):
        button = ttk.Checkbutton(parent, text=text, variable=variable, command=command)
        button.grid(row=row, column=0, columnspan=4, sticky="w", pady=(self.pad // 2, 0))
        return button

    def _button(self, parent, text, command, **pack):
        button = ttk.Button(parent, text=text, command=command)
        button.pack(side=pack.pop("side", "right"), padx=(self.pad // 2, 0), **pack)
        self.action_buttons.append(button)
        return button

    def _path_field(self, parent, row, label, key, title, kind="dir", filetypes=(), buttons=()):
        """Label, entry, Browse button and a found / not-found note under it. Returns the next free row."""
        if label:
            ttk.Label(parent, text=label).grid(row=row, column=0, columnspan=4, sticky="w", pady=(self.pad, 2))
            row += 1
        ttk.Entry(parent, textvariable=self.vars[key]).grid(row=row, column=0, sticky="ew")
        for column, (text, command) in enumerate(
            (*buttons, ("Browse...", lambda: self._browse(key, title, kind, filetypes))), start=1
        ):
            ttk.Button(parent, text=text, command=command).grid(row=row, column=column, padx=(self.pad // 2, 0))
        note = tk.StringVar(self.root)
        label = WrapLabel(parent, textvariable=note)
        label.grid(row=row + 1, column=0, columnspan=4, sticky="ew")
        self.path_checks[key] = (note, label)
        self.vars[key].trace_add("write", lambda *_: self._check_path(key))
        self._check_path(key)
        return row + 2

    def _image_button(self, key, title):
        """An "Image..." button choosing a disc image for a disc field, where the back end can mount one."""
        if not self.backend.disc_images:
            return ()
        return (("Image...", lambda: self._browse(key, title, "file", (("Disc images", "*.iso *.mds *.mdf"),))),)

    def _check_path(self, key):
        note, label = self.path_checks[key]
        ok, text = self.backend.check_path(key, self.vars[key].get())
        note.set("" if ok is None else ("✓ " + text if ok else "✗ " + text))
        label.configure(style="Good.TLabel" if ok else "Bad.TLabel")
        if ok is None:
            label.grid_remove()
        else:
            label.grid()

    def _browse(self, key, title, kind, filetypes):
        if kind == "dir":
            selected = filedialog.askdirectory(parent=self.root, title=title)
        else:
            selected = filedialog.askopenfilename(
                parent=self.root, title=title, filetypes=(*filetypes, ("All files", "*"))
            )
        if selected:
            self.vars[key].set(selected)

    # --- header and bottom strip ---------------------------------------------------------------------
    def _build_header(self):
        header = ttk.Frame(self.root, padding=(self.pad, self.pad, self.pad, self.pad // 2))
        header.pack(fill="x")
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text=self.backend.location_label).grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Entry(header, textvariable=self.vars["location"]).grid(row=1, column=0, sticky="ew", pady=2)
        ttk.Button(
            header, text="Browse...",
            command=lambda: self._browse("location", self.backend.location_title, "dir", ()),
        ).grid(row=1, column=1, padx=(self.pad // 2, 0))
        WrapLabel(header, textvariable=self.header_status, style="Heading.TLabel").grid(
            row=2, column=0, columnspan=2, sticky="ew", pady=(self.pad // 2, 0)
        )

    def _build_bottom(self):
        bottom = ttk.Frame(self.root, padding=(self.pad, self.pad // 2, self.pad, self.pad))
        bottom.pack(side="bottom", fill="x")
        row = ttk.Frame(bottom)
        row.pack(fill="x")
        WrapLabel(row, textvariable=self.status).pack(side="left", fill="x", expand=True)
        self.log_button = ttk.Button(row, text="Show details", command=self.toggle_log)
        self.log_button.pack(side="right", padx=(self.pad, 0))
        self.progress = ttk.Progressbar(bottom, mode="indeterminate")
        self.log = scrolledtext.ScrolledText(bottom, height=7, state="disabled", wrap="word")
        self.bottom = bottom

    def toggle_log(self, show=None):
        show = not self.log.winfo_ismapped() if show is None else show
        if show:
            self.log.pack(fill="both", expand=True, pady=(self.pad // 2, 0))
        else:
            self.log.pack_forget()
        self.log_button.configure(text="Hide details" if show else "Show details")

    def write_log(self, message):
        self.log.configure(state="normal")
        self.log.insert("end", str(message).rstrip() + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    # --- pages -------------------------------------------------------------------------------------------
    def _build_play(self, page):
        content = page.content
        timing = self._section(content, "Frame rate")
        for column, (label, key) in enumerate((("Menus", "menu_fps"), ("Simulation", "sim_fps"))):
            ttk.Label(timing, text=label).grid(row=0, column=column * 2, sticky="w")
            ttk.Combobox(timing, textvariable=self.vars[key], values=("30", "60"), state="readonly",
                         width=6).grid(row=0, column=column * 2 + 1, sticky="w", padx=(self.pad // 2, self.pad * 3))
        timing.columnconfigure(0, weight=0)
        timing.columnconfigure(4, weight=1)
        WrapLabel(timing, text="30 FPS is recommended. 60 FPS in the simulation may cause gameplay or timing "
                               "glitches.", style="Note.TLabel").grid(
            row=1, column=0, columnspan=5, sticky="ew", pady=(self.pad // 2, 0))

        renderer = self._section(content, "Renderer")
        self.renderer_combo = ttk.Combobox(renderer, textvariable=self.renderer_label, state="readonly")
        self.renderer_combo.grid(row=0, column=0, sticky="ew")
        self.renderer_combo.bind("<<ComboboxSelected>>", lambda _event: self._update_resolution_state())
        ttk.Label(renderer, text="Direct3D 9 renderer resolution (WIDTHxHEIGHT; blank uses its default, the "
                                 "window's size with Borderless full screen)").grid(
            row=1, column=0, sticky="w", pady=(self.pad, 2))
        self.resolution_entry = ttk.Entry(renderer, textvariable=self.vars["resolution"], width=16)
        self.resolution_entry.grid(row=2, column=0, sticky="w")

        if "display" in self.backend.play_sections:
            self._build_display(content)
        self._note(content, text="The fixes ticked on the Fixes page are applied by Apply & Play.")
        if self.backend.can_stop:
            self.stop_button = ttk.Button(page.actions, text="Stop game", command=self.stop_game,
                                          state="disabled")
            self.stop_button.pack(side="right", padx=(self.pad // 2, 0))
        self._button(page.actions, "Play without changes", self.play)
        self._button(page.actions, "Apply & Play", self.apply_and_play)

    def _build_display(self, content):
        display = self._section(content, "Display")
        self._check(display, 0, "Scale to full screen with gamescope", self.vars["gamescope"],
                    self._update_display_state)
        options = ttk.Frame(display)
        options.grid(row=1, column=0, sticky="w", pady=(self.pad // 2, 0))
        self.display_widgets = []
        for column, (label, key, values) in enumerate((
            ("Scaling", "scale", self.backend.scale_choices),
            ("Filter", "filter", self.backend.filter_choices),
        )):
            ttk.Label(options, text=label).grid(row=0, column=column * 2, sticky="w")
            combo = ttk.Combobox(options, textvariable=self.vars[key], values=values, state="readonly", width=9)
            combo.grid(row=0, column=column * 2 + 1, padx=(self.pad // 2, self.pad * 3))
            self.display_widgets.append((combo, "readonly"))
        ttk.Label(display, text="Game screen size under gamescope (blank = 640x480; match the Direct3D 9 "
                                "renderer's resolution)").grid(row=2, column=0, sticky="w", pady=(self.pad, 2))
        entry = ttk.Entry(display, textvariable=self.vars["gamescope_resolution"], width=16)
        entry.grid(row=3, column=0, sticky="w")
        self.display_widgets.append((entry, "normal"))
        ttk.Label(display, text="Or play in a Wine window of this size instead (WIDTHxHEIGHT; blank = off)").grid(
            row=4, column=0, sticky="w", pady=(self.pad, 2))
        ttk.Entry(display, textvariable=self.vars["virtual_desktop"], width=16).grid(row=5, column=0, sticky="w")
        self._update_display_state()

    def _build_fixes(self, page):
        content = page.content
        self._note(content, text="Apply & Play and Install & update apply the ticked fixes. Each box starts "
                                 "at the patcher's default for this system. The cutscene and music fixes also "
                                 "need the disc 2 folder chosen on the Install & update page.")
        box = self._section(content, "Community fixes")
        self.fix_checks = {}
        version = installed_version(self.backend.game_folder(self.vars["location"].get()))
        row = 0
        for fix in self.backend.fixes(version):
            default = "on" if fix.default else "off"
            command = self._on_disc2_toggled if fix.name in DISC2_FIXES else None
            self.fix_checks[fix.name] = self._check(box, row, f"{fix.label} (default: {default})",
                                                    self.fix_vars[fix.name], command)
            WrapLabel(box, text=fix.description, style="Note.TLabel").grid(
                row=row + 1, column=0, columnspan=4, sticky="ew", padx=(self.pad * 4, 0))
            row += 2

    def _build_install(self, page):
        content = page.content
        self.install_mode_label = self._note(content, textvariable=self.install_mode, style="TLabel")
        self.requirements_label = self._note(content, textvariable=self.requirements, style="Bad.TLabel")

        files = self._section(content, "Game files")
        disc1 = ("Disc 1 drive, folder or disc image: .iso or .mds/.mdf (needed for a new install)"
                 if self.backend.disc_images else "Disc 1 drive or folder (needed for a new install)")
        row = self._path_field(files, 0, disc1, "disc1", "Select the Heavy Gear disc 1 drive or a folder copy of it",
                               buttons=self._image_button("disc1", "Select a Heavy Gear disc 1 image"))
        if "disc2_folder" in self.backend.install_sections:
            row = self._path_field(
                files, row, "Disc 2 folder (needed for a new install; also used to play without the disc in "
                            "a drive)", "disc2", "Select the disc 2 folder")
        ttk.Label(files, text="Controls").grid(row=row, column=0, sticky="w", pady=(self.pad, 2))
        self.controls_combo = ttk.Combobox(files, textvariable=self.vars["controls"], state="readonly", width=16)
        self.controls_combo.grid(row=row + 1, column=0, sticky="w")

        patches = self._section(content, "Official updates (optional)")
        self._note(patches, 0, text="Patch files are not included. Browse to files you already have; files "
                                    "beside this app are found automatically. " + self.backend.patch_note)
        row = 1
        for version, key in (("1.1", "11"), ("1.2", "12")):
            self._check(patches, row, f"Apply the official {version} update", self.vars[f"apply{key}"])
            row = self._path_field(patches, row + 1, "", f"patch{key}",
                                   "Select the official Heavy Gear patch executable", "file",
                                   (("Windows executables", "*.exe *.EXE"),))

        options = self._section(content, "Fixes and renderer")
        self._check(options, 0, "Apply the fixes from the Fixes page and the frame rates from the Play page",
                    self.vars["apply_fixes"])
        self._check(options, 1, "Install and select the Direct3D 9 renderer (needs official 1.2)",
                    self.vars["install_renderer"], self._renderer_touched)

        if "cutscenes" in self.backend.install_sections:
            media = self._section(content, "Cutscene support")
            self._check(media, 0, "Install Indeo 5 and the game fonts (asks for administrator approval)",
                        self.vars["install_media"])
            if self.backend.indeo_installed():
                self.indeo_tip = self._note(media, 1, style="Good.TLabel",
                                            text="✓ Indeo 5 is already installed in Windows, so the cutscenes can "
                                                 "play. Tick this only to install the game fonts again.")
            self._note(media, 2, text="If Windows does not have Indeo 5 yet, it is extracted from disc 1 when "
                                      "unshield is installed; otherwise select an extracted ir50_32.dll. The "
                                      "disc is never changed.")
            self._path_field(media, 3, "", "codec_path", "Select the extracted Indeo 5 codec", "file",
                             (("32-bit Indeo codec", "ir50_32.dll"), ("DLL files", "*.dll")))
        if "disc2_copy" in self.backend.install_sections:
            disc2 = self._section(content, "Play without disc 2")
            self._note(disc2, 0, text="The game needs disc 2 in the drive for its cutscenes and CD music. Tick "
                                      "the cutscene or music fix on the Fixes page, and choose the disc 2 folder "
                                      "here to copy the cutscenes and rip the music from.")
            row = self._path_field(disc2, 1, "Disc 2 drive, folder or disc image (a .iso has the cutscenes "
                                             "but not the CD music; an .mds/.mdf has both)", "disc2",
                                   "Select the Heavy Gear disc 2 drive or a folder copy of it",
                                   buttons=(("Find disc", self.find_disc2),
                                            *self._image_button("disc2", "Select a Heavy Gear disc 2 image")))
            self._path_field(disc2, row, "Or use music you already ripped: a folder of TRACK02.WAV, "
                                         "TRACK03.WAV, ... files", "music_folder",
                             "Select the folder of ripped TRACKnn files")
        if "glide" in self.backend.install_sections:
            glide = self._section(content, "3Dfx (Glide)")
            self._check(glide, 0, "Set up 3Dfx (Glide) support with the particle fix", self.vars["install_glide"],
                        self._update_requirements)
            self._note(glide, 1, text="Glide driver: a folder holding the dgVoodoo2 2.79 and DXVK archives, or a "
                                      "glide2x.dll. Leave it empty to keep a driver already in the game folder.")
            self._path_field(glide, 2, "", "glide_driver", "Select the folder with the wrapper archives")
        if "glide_copy" in self.backend.install_sections:
            glide = self._section(content, "3Dfx (Glide)")
            check = self._check(glide, 0, "Set up 3Dfx: copy a Glide driver into the game folder, with the particle "
                                          "fix", self.vars["install_glide"])
            hint = ttk.Label(glide, text="Where do I get it? (hover here)", style="Note.TLabel",
                             cursor="question_arrow")
            hint.grid(row=1, column=0, columnspan=4, sticky="w")
            for widget in (check, hint):
                Tooltip(widget, GLIDE_HELP)
            self._note(glide, 2, text="glide2x.dll from nGlide or dgVoodoo2. nGlide's copy in Windows' SysWOW64 "
                                      "folder is found automatically.")
            self._path_field(glide, 3, "", "glide_driver", "Select glide2x.dll (nGlide or dgVoodoo2)", "file",
                             (("Glide driver", "glide2x.dll"), ("DLL files", "*.dll")))
        self._button(page.actions, "Install / Update", self.start_install)

    def _build_tools(self, page):
        content = page.content
        backup = self._section(content, "Backups")
        self._note(backup, 0, text="A backup is a compressed copy of the whole Wine prefix, kept in "
                                   f"{self.backend.backups_dir()}. Restoring moves the current prefix aside.")
        buttons = ttk.Frame(backup)
        buttons.grid(row=1, column=0, sticky="w", pady=(self.pad // 2, 0))
        self._button(buttons, "Back up the prefix", self.backup, side="left")
        self._button(buttons, "Restore a backup...", self.restore, side="left")
        menu = self._section(content, "Applications menu")
        self._note(menu, 0, text="Adds Heavy Gear to your desktop's applications menu, starting this app.")
        holder = ttk.Frame(menu)
        holder.grid(row=1, column=0, sticky="w", pady=(self.pad // 2, 0))
        self._button(holder, "Add to applications menu", self.add_menu_entry, side="left")

    def _fit(self):
        """Size the pages to their content, but keep the whole window (log open) on the screen."""
        self.toggle_log(True)
        self.root.update_idletasks()
        width = max(page.content.winfo_reqwidth() for page in self.pages.values())
        for page in self.pages.values():
            page.canvas.configure(width=width)
        self.root.update()                    # let the labels wrap to that width before measuring heights
        height = max(page.content.winfo_reqheight() for page in self.pages.values())
        for page in self.pages.values():
            page.canvas.configure(height=height)
        self.root.update_idletasks()
        limit = self.root.winfo_screenheight() - max(100, self.root.winfo_screenheight() // 8)
        excess = self.root.winfo_reqheight() - limit
        if excess > 0:
            for page in self.pages.values():
                page.canvas.configure(height=max(self.pad * 10, height - excess))
        self.toggle_log(False)
        self.root.update_idletasks()
        self.root.minsize(min(self.root.winfo_reqwidth(), 480), min(self.root.winfo_reqheight(), 360))

    # --- state -----------------------------------------------------------------------------------------
    def show_page(self, name):
        self.notebook.select(self.pages[name])

    def current_page(self):
        selected = self.notebook.select()
        return next(name for name, page in self.pages.items() if str(page) == selected)

    def choices(self):
        choices = {key: variable.get() for key, variable in self.vars.items()}
        choices["fixes"] = {name: variable.get() for name, variable in self.fix_vars.items()}
        choices["renderer"] = self.renderer_files.get(self.renderer_label.get(), "")
        return choices

    def _schedule_refresh(self):
        if not self._refresh_pending:
            self._refresh_pending = True
            self.root.after(300, self.refresh)

    def refresh(self):
        """Re-read the game at the chosen location: status line, renderer list, install mode."""
        self._refresh_pending = False
        info = self.backend.describe_game(self.vars["location"].get())
        self.renderer_files = {}
        labels = [KEEP_RENDERER]
        for filename in info.renderers:
            label = renderer_label(filename)
            self.renderer_files[label] = filename
            labels.append(label)
        selected = next((label for label, filename in self.renderer_files.items()
                         if filename.casefold() == info.renderer.casefold()), KEEP_RENDERER)
        self.renderer_combo.configure(values=labels)
        self.renderer_label.set(selected)
        self.vars["resolution"].set(info.resolution)
        self._update_resolution_state()
        for name in ("partdepth", "borderless"):     # the patcher has these for the official 1.2 only
            if name in self.fix_checks:
                self.fix_checks[name].configure(state="disabled" if info.version == "1.0" else "normal")
        if info.found:
            version = f"version {info.version}" if info.version else "an unknown version"
            renderer = renderer_label(info.renderer) if info.renderer else "the game's default"
            self.header_status.set(f"Heavy Gear ({version}) is installed in {info.game}. Renderer: {renderer}.")
            self.install_mode.set("The game is installed here: its files are kept. Choose what to add or update, "
                                  "then click Install / Update.")
            self.controls_combo.configure(values=EXISTING_CONTROLS)
            if self.vars["controls"].get() not in EXISTING_CONTROLS:
                self.vars["controls"].set("keep existing")
        else:
            self.header_status.set(f"No game found in {info.game or 'this location'}. Install it on the Install & "
                                   "update page, or choose the folder where it is.")
            self.install_mode.set("To install a new copy, select your disc 1 (a drive or a folder copy), choose "
                                  "the controls, then click Install / Update.")
            self.controls_combo.configure(values=NEW_CONTROLS)
            if self.vars["controls"].get() not in NEW_CONTROLS:
                self.vars["controls"].set("action")
        self._update_requirements()

    def _update_requirements(self):
        missing = self.backend.missing_programs(self.choices())
        self.requirements.set("\n".join(missing))
        if missing:
            self.requirements_label.pack(fill="x", pady=(0, self.pad), after=self.install_mode_label)
        else:
            self.requirements_label.pack_forget()

    def _update_resolution_state(self):
        enabled = self.renderer_files.get(self.renderer_label.get(), "").casefold() == HG_RENDERER
        self.resolution_entry.configure(state="normal" if enabled else "disabled")

    def _update_display_state(self):
        on = self.vars["gamescope"].get()
        for widget, state in self.display_widgets:
            widget.configure(state=state if on else "disabled")

    def _renderer_touched(self):
        self.vars["renderer_touched"].set(True)
        self._update_requirements()

    def _on_disc2_toggled(self):
        # Part of the project's fixes (hgfix re-applies the whole set each run), so keep that box on.
        if any(self.fix_vars[name].get() for name in ("nodisc", "music")):
            self.vars["apply_fixes"].set(True)

    # --- running work in the background ----------------------------------------------------------------
    def _set_busy(self, busy):
        self.busy = busy
        for button in self.action_buttons:
            button.configure(state="disabled" if busy else "normal")
        if busy:
            self.progress.pack(fill="x", pady=(self.pad // 2, 0), after=self.log_button.master)
            self.progress.start(15)
        else:
            self.progress.stop()
            self.progress.pack_forget()
            if self.backend.can_stop:
                self.stop_button.configure(state="disabled")

    def run_job(self, title, work, on_success=None):
        """Run work(report) on a worker thread. report(line) logs a line and shows it as the status."""
        self._set_busy(True)
        self.status.set(title)
        self.write_log(title)

        def report(line):
            self.jobs.put(("line", line))

        def target():
            try:
                self.jobs.put(("done", work(report)))
            except BaseException as exc:  # always report back, or the window stays locked
                self.jobs.put(("error", exc))

        threading.Thread(target=target, daemon=True).start()
        self.root.after(100, lambda: self._poll(on_success))

    def _poll(self, on_success):
        while True:
            try:
                kind, value = self.jobs.get_nowait()
            except queue.Empty:
                self.root.after(100, lambda: self._poll(on_success))
                return
            if kind == "started":
                self.stop_button.configure(state="normal")
                continue
            if kind == "line":
                for line in str(value).splitlines() or [""]:
                    if line.strip():
                        self.write_log(line)
                        self.status.set(line.strip())
                continue
            self._set_busy(False)
            if self.close_when_done:
                self.root.destroy()
                return
            if kind == "done":
                if on_success:
                    on_success(value)
            else:
                self.report_error(value)
            return

    def report_error(self, exc):
        message = self.backend.describe_error(exc)
        self.write_log("Error: " + message)
        self.status.set("That did not work: " + message.splitlines()[0])
        messagebox.showerror(TITLE, message, parent=self.root)

    def _game_started(self, _process):
        """The game's process is running (worker thread): enable Stop game."""
        if self.backend.can_stop:
            self.jobs.put(("started", None))

    def close(self):
        if not self.busy:
            self.root.destroy()
        elif self.backend.can_stop:
            if messagebox.askyesno(TITLE, "Something is still running. Stop it and close? The window closes once the current step has stopped.", parent=self.root):
                self.close_when_done = True
                self.backend.stop()
        else:
            messagebox.showwarning(TITLE, "Wait for the current step to finish before closing this window.",
                                   parent=self.root)

    # --- actions -----------------------------------------------------------------------------------------
    def _plan(self, plan):
        try:
            return plan(self.choices())
        except (OSError, RuntimeError, ValueError) as exc:
            self.report_error(exc)
            return None

    def apply_and_play(self):
        if self.busy:
            return
        plan = self._plan(self.backend.plan_apply)
        if plan is None:
            return
        self.backend.save_settings(self.choices())

        def work(report):
            report("Applying the fixes and renderer settings...")
            self.backend.apply(plan, report)
            report("Starting Heavy Gear...")
            self.backend.play(plan, report, self._game_started)

        self.run_job("Applying the fixes and renderer settings...", work, lambda _: self._played())

    def play(self):
        if self.busy:
            return
        plan = self._plan(self.backend.plan_play)
        if plan is None:
            return
        self.backend.save_settings(self.choices())
        self.run_job("Starting Heavy Gear...", lambda report: self.backend.play(plan, report, self._game_started),
                     lambda _: self._played())

    def _played(self):
        self.status.set("Heavy Gear exited." if self.backend.can_stop else "Heavy Gear started.")
        self.refresh()

    def stop_game(self):
        self.backend.stop()
        self.write_log("Stopping Heavy Gear...")

    def start_install(self):
        if self.busy:
            return
        try:
            config = self.backend.validate_install(self.choices())
        except Exception as exc:  # validation errors, but never leave a click with no response
            self.report_error(exc)
            return
        try:
            self.backend.save_settings(self.choices())
            start = not any(version == "1.1" for version, *_ in config["patches"]) or messagebox.askyesno(
                TITLE,
                "The official 1.1 update opens Heavy Gear when it finishes.\n\n"
                "Press Esc once the game opens to close it, so the install can continue.\n\n"
                "Apply the official 1.1 update now?",
                parent=self.root,
            )
        except BaseException:
            self.backend.cancel_install(config)
            raise
        if not start:
            self.backend.cancel_install(config)
            self.status.set("Install cancelled.")
            return
        self.toggle_log(True)
        self.run_job("Installing and updating...", lambda report: self.backend.run_install(config, report),
                     self._installed)

    def _installed(self, result):
        note, game = result
        self.backend.save_settings(self.choices())
        self.refresh()
        self.status.set(f"Install finished. {note}")
        messagebox.showinfo(TITLE, f"Install finished.\n\nGame folder: {game}\n\n{note}", parent=self.root)
        self.show_page("play")

    def find_disc2(self):
        import disc2_media

        found = disc2_media.detect_disc2()
        if found:
            self.vars["disc2"].set(found)
        else:
            messagebox.showinfo(
                TITLE,
                "Disc 2 was not found in a CD/DVD drive. Put it in the drive (disc 2 has the VIDEO folder), "
                "or Browse to a folder copy of it.",
                parent=self.root,
            )

    def backup(self):
        if self.busy:
            return
        location = self.vars["location"].get()
        self.run_job("Backing up the prefix (this can take a minute)...",
                     lambda report: self.backend.backup(location, report))

    def restore(self):
        if self.busy:
            return
        folder = Path(self.backend.backups_dir())
        folder.mkdir(parents=True, exist_ok=True)
        chosen = filedialog.askopenfilename(
            parent=self.root, title="Choose a prefix backup to restore", initialdir=str(folder),
            filetypes=(("Prefix backups", "*.tar.zst"), ("All files", "*")))
        if not chosen or not messagebox.askyesno(
                TITLE, "Restore this backup? The current prefix is moved aside, not deleted.\n\n" + chosen,
                parent=self.root):
            return
        location = self.vars["location"].get()
        self.run_job("Restoring the backup...",
                     lambda report: self.backend.restore(chosen, location, report),
                     lambda _: self.refresh())

    def add_menu_entry(self):
        try:
            entry = self.backend.add_menu_entry()
        except OSError as exc:
            self.report_error(exc)
            return
        self.write_log(f"Added {entry}")
        self.status.set("Added Heavy Gear to the applications menu.")
