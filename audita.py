"""audita 1.0 — desktop tool for acoustic segment validation.

Run with: python audita.py
"""
import csv
import sys
import ctypes
import os
import re
import time
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk
import numpy as np
import soundfile as sf
from PIL import Image, ImageTk, ImageDraw, ImageFont
from scipy.signal import spectrogram

try:
    import sounddevice as sd
except ImportError:
    sd = None


CATEGORIES = ("positive", "negative", "uncertain", "reassigned", "multitaxa")
COLUMNS = [
    "observationID", "mediaID", "scientificNameProposed", "validationCategory",
    "scientificNameValidated", "classifiedBy", "favorite", "fileName", "validationComment"
]
AUDIO_EXT = {".wav", ".wave", ".flac", ".ogg"}
ALL_SPECIES = "All species"
UNKNOWN_SPECIES = "Unknown species"
# ============================================================
# CUSTOMIZATION: EDIT HEX COLOR VALUES HERE
# ============================================================
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# Requested classification colors (legacy constant names retained for compatibility)
VERDE_POSITIVO = "#F288A9"
VERDE_POSITIVO_HOVER = "#DE7D9C"
ROJO_NEGATIVO = "#07111F"
ROJO_NEGATIVO_HOVER = "#162131"
AMARILLO_INCIERTO = "#E5E7EB"
AMARILLO_INCIERTO_HOVER = "#D7DCE2"
VIOLETA_REASIGNADO = "#E5E7EB"
VIOLETA_REASIGNADO_HOVER = "#D7DCE2"
AZUL_MULTITAXA = "#E5E7EB"
AZUL_MULTITAXA_HOVER = "#D7DCE2"

# Actions and controls
AZUL_BOTONES = "#8E9350"
AZUL_BOTONES_HOVER = "#7C8247"

# Shared buttons: exact PamFlow green palette.
VERDE_PAMFLOW = "#687030"
VERDE_PAMFLOW_HOVER = "#565D28"
GRIS_NAVEGACION = "#636B75"
GRIS_NAVEGACION_HOVER = "#747D88"
FONDO_SPECTROGRAM = "#070B1D"
COLOR_LINEA_REPRODUCCION = "#22D3EE"
COLOR_ESTRELLA = "#FBD58C"

# Fonts: edit here (no interface controls)
FUENTE_APP = "Helvetica"
FUENTE_EJES = "DejaVu Sans"
TAMANO_EJES = 22

CATEGORY_INFO = {
    "positive": {"label": "Positive", "color": VERDE_POSITIVO, "hover": VERDE_POSITIVO_HOVER, "text": "#FFFFFF"},
    "negative": {"label": "Negative", "color": ROJO_NEGATIVO, "hover": ROJO_NEGATIVO_HOVER, "text": "#FFFFFF"},
    "uncertain": {"label": "Uncertain", "color": AMARILLO_INCIERTO, "hover": AMARILLO_INCIERTO_HOVER, "text": "#1F2937"},
    "reassigned": {"label": "Reassigned", "color": VIOLETA_REASIGNADO, "hover": VIOLETA_REASIGNADO_HOVER, "text": "#1F2937"},
    "multitaxa": {"label": "Multitaxa", "color": AZUL_MULTITAXA, "hover": AZUL_MULTITAXA_HOVER, "text": "#1F2937"},
}


def extract_metadata(filename):
    stem = Path(filename).stem
    match = re.match(r"^(.+?)_(\d+(?:\.\d+)?)[sS]?_(\d+(?:\.\d+)?)[sS]?$", stem)
    if not match:
        return stem, "", ""
    prefix, start, end = match.groups()
    if float(end) <= float(start):
        return stem, "", ""
    prefix_match = re.match(r"^\d+\.\d+_(?:\d+_)?(.+)$", prefix)
    media_id = prefix_match.group(1) if prefix_match else prefix
    return media_id, start, end


def detected_species(folder, filepath):
    candidates = list(filepath.relative_to(folder).parts[:-1][::-1]) + [folder.name]
    for candidate in candidates:
        if re.fullmatch(r"[A-Z][a-z]+_[a-z][a-z-]+(?:_[a-z]+)?", candidate):
            return candidate.replace("_", " ")
    return ""


def confidence_sort_key(path):
    """Sort by the numeric confidence prefix descending; unknown prefixes go last."""
    match = re.match(r"^(\d+(?:\.\d+)?)_", path.name)
    if match:
        return (0, -float(match.group(1)), str(path).casefold())
    return (1, 0.0, str(path).casefold())


def observation_id(filename):
    media_id, start, end = extract_metadata(filename)
    return f"{media_id}_{start}_{end}" if start and end else media_id


def magma_colors(norm):
    """Approximate matplotlib magma palette using piecewise interpolation."""
    stops = np.array([
        [0.001, 0.000, 0.014],
        [0.115, 0.066, 0.274],
        [0.316, 0.071, 0.485],
        [0.573, 0.157, 0.502],
        [0.816, 0.278, 0.471],
        [0.973, 0.555, 0.322],
        [0.987, 0.843, 0.555],
    ], dtype=float)
    positions = np.linspace(0.0, 1.0, len(stops))
    flat = norm.reshape(-1)
    rgb = np.empty((flat.size, 3), dtype=float)
    for i in range(3):
        rgb[:, i] = np.interp(flat, positions, stops[:, i])
    rgb = np.clip(rgb * 255, 0, 255).astype("uint8")
    return rgb.reshape(norm.shape + (3,))


class ValidatorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("audita 1.0 — Segment validation tool")
        self.root.geometry("1440x900")
        self.root.minsize(1200, 700)
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.folder = None
        self.files = []
        self.index = 0
        self.species_by_file = {}
        self.visible_indices = []
        self.rows = {}
        self.audio = None
        self.sr = None
        self.playing = False
        self.playback_start = 0.0
        self.playback_job = None
        self.photo = None
        self.logo_photo = None
        self.category_buttons = {}
        self.history = []
        self.completion_notified = False
        self.favorites = set()
        self.autoplay_var = tk.BooleanVar(value=False)
        self.logo_filename = "logo_audita.png"

        self.species_filter_var = tk.StringVar(value=ALL_SPECIES)
        self.name_var = tk.StringVar()
        self.category_var = tk.StringVar()
        self.species_var = tk.StringVar()
        self.favorite_var = tk.BooleanVar()
        self.file_var = tk.StringVar()
        self.progress_var = tk.StringVar(value="Open a folder to get started")
        self.meta_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Supports WAV, FLAC and OGG; works offline")
        self.axis_font_size = TAMANO_EJES

        self._ui()
        self.name_var.trace_add("write", lambda *_: self.update_interface_lock())
        self.update_interface_lock()
        self.setup_app_icon()
        self.load_default_logo()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.install_shortcuts()

    def _typing_in_field(self, event):
        """Preserve normal typing, navigation and editing in text fields."""
        widget = event.widget
        return isinstance(widget, (tk.Entry, tk.Text, tk.Spinbox))

    def _shortcut(self, event, action, *, allow_in_fields=False):
        if self._typing_in_field(event) and not allow_in_fields:
            return None
        action()
        return "break"

    def install_shortcuts(self):
        """Letter shortcuts; classification is never triggered while typing."""
        mappings = {
            "<KeyPress-p>": lambda: self.set_category("positive"),
            "<KeyPress-n>": lambda: self.set_category("negative"),
            "<KeyPress-u>": lambda: self.set_category("uncertain"),
            "<KeyPress-r>": lambda: self.set_category("reassigned"),
            "<KeyPress-m>": lambda: self.set_category("multitaxa"),
            "<KeyPress-P>": lambda: self.set_category("positive"),
            "<KeyPress-N>": lambda: self.set_category("negative"),
            "<KeyPress-U>": lambda: self.set_category("uncertain"),
            "<KeyPress-R>": lambda: self.set_category("reassigned"),
            "<KeyPress-M>": lambda: self.set_category("multitaxa"),
            "<space>": self.toggle_play,
            "<Left>": lambda: self.navigate(-1),
            "<Right>": lambda: self.navigate(1),
            "<Control-z>": self.undo_classification,
            "<Control-Z>": self.undo_classification,
            "<Control-s>": self.save,
            "<Control-o>": self.open_folder,
            "<Control-Shift-S>": self.export_as,
            "<F1>": self.show_shortcuts,
        }
        for sequence, command in mappings.items():
            self.root.bind(sequence, lambda event, cmd=command:
                           self._shortcut(event, cmd))

    def show_shortcuts(self):
        messagebox.showinfo(
            "Keyboard shortcuts",
            "P   Positive\n"
            "N   Negative\n"
            "U   Uncertain\n"
            "R   Reassigned\n"
            "M   Multitaxa\n"
            "Space   Play / Stop\n"
            "← / →   Previous / Next\n"
            "Ctrl+Z   Undo classification\n"
            "Ctrl+S   Save\n"
            "Ctrl+O   Open folder\n"
            "Ctrl+Shift+S   Export CSV\n"
            "Enter   Confirm scientific name\n"
            "F1   Show shortcuts\n\n"
            "Shortcuts are paused while typing in text fields."
        )

    def validator_ready(self):
        return bool(self.name_var.get().strip())

    def update_interface_lock(self):
        ready = self.validator_ready()
        if not ready and self.playing:
            self.stop()
        state = "normal" if ready else "disabled"
        self.open_button.configure(state=state)
        self.species_combo.configure(state="readonly" if ready else "disabled")
        self.combo.configure(state="readonly" if ready else "disabled")
        self.undo_button.configure(state=state)
        self.skip_button.configure(state=state)
        self.pending_button.configure(state=state)
        self.prev_button.configure(state=state)
        self.play_button.configure(state=state)
        self.next_button.configure(state=state)
        self.autoplay_toggle.configure(state=state)
        self.export_button_bottom.configure(state=state)
        for button in self.category_buttons.values():
            button.configure(state=state)
        self.species_entry.configure(
            state="normal" if ready and self.category_var.get() in ("reassigned", "multitaxa") else "disabled"
        )
        self.comment_entry.configure(state="normal" if ready else "disabled")
        self.status_var.set(
            "Enter the validator name to unlock audita"
            if not ready else
            (f"{len(self.audio)/self.sr:.2f} s · {self.sr:,} Hz" if self.audio is not None and self.sr else "Ready to validate")
        )

    def app_font(self, size=14, weight="normal"):
        return ctk.CTkFont(family=FUENTE_APP, size=size, weight=weight)

    def _ui(self):
        self.frame = ctk.CTkFrame(self.root, fg_color="transparent")
        self.frame.pack(fill="both", expand=True, padx=14, pady=12)

        # Encabezado compacto
        header = ctk.CTkFrame(self.frame, fg_color="#242424", corner_radius=10)
        header.pack(fill="x", pady=(0, 2))
        self.logo_area = ctk.CTkLabel(header, text="LOGO PLACEHOLDER", width=295,
                                      font=self.app_font(16, "bold"), text_color=("#506174", "#A9BBCD"))
        self.logo_area.pack(side="left", padx=(10, 6), pady=2)

        # One horizontal toolbar: validator, folder, species and segment.
        top = ctk.CTkFrame(self.frame, fg_color="transparent")
        top.pack(fill="x", pady=(0, 2))
        self.validator_label = ctk.CTkLabel(top, text="Validator *:", font=self.app_font(14, "bold"))
        self.validator_label.pack(side="left", padx=(2, 6))
        self.name_entry = ctk.CTkEntry(top, textvariable=self.name_var, width=175, font=self.app_font(14))
        self.name_entry.pack(side="left", padx=(0, 12))
        self.open_button = ctk.CTkButton(top, text="📁 Open folder", width=137,
                                         fg_color=AZUL_BOTONES, hover_color=AZUL_BOTONES_HOVER,
                                         text_color="#FFFFFF",
                                         command=self.open_folder, font=self.app_font(14, "bold"))
        self.open_button.pack(side="left", padx=(0, 12))
        self.species_label = ctk.CTkLabel(top, text="Proposed species:", font=self.app_font(14, "bold"))
        self.species_label.pack(side="left", padx=(0, 6))
        self.species_combo = ctk.CTkComboBox(top, variable=self.species_filter_var, width=190,
                                             state="readonly", command=lambda _value: self.filter_species(),
                                             font=self.app_font(13), dropdown_font=self.app_font(13))
        self.species_combo.pack(side="left", padx=(0, 12))
        self.segment_label = ctk.CTkLabel(top, text="Segment:", font=self.app_font(14, "bold"))
        self.segment_label.pack(side="left", padx=(0, 6))
        self.combo = ctk.CTkComboBox(top, variable=self.file_var, state="readonly", width=280,
                                     command=lambda _value: self.select_from_menu(),
                                     font=self.app_font(12), dropdown_font=self.app_font(12))
        self.combo.pack(side="left", fill="x", expand=True)

        # Metadata remains on the second line, so the four controls stay together.
        self.meta_label = ctk.CTkLabel(self.frame, textvariable=self.meta_var, anchor="w",
                                       text_color=("#506174", "#A9BBCD"), font=self.app_font(13))
        self.meta_label.pack(fill="x", pady=(0, 3))

        main = ctk.CTkFrame(self.frame, fg_color="transparent")
        main.pack(fill="both", expand=True)
        # 60% spectrogram + summary, 40% classification.
        main.grid_columnconfigure(0, weight=3, uniform="main-panels")
        main.grid_columnconfigure(1, weight=2, uniform="main-panels")
        main.grid_rowconfigure(0, weight=1)

        self.left = ctk.CTkFrame(main, corner_radius=14)
        self.left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self.right = ctk.CTkFrame(main, corner_radius=14)
        self.right.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        self.right.grid_columnconfigure(0, weight=1)
        self.right.grid_rowconfigure(5, weight=1)

        self.plot_title = ctk.CTkLabel(self.left, text="spectrogram", font=self.app_font(14, "bold"))
        self.plot_title.pack(anchor="w", padx=14, pady=(12, 4))
        plot_area = ctk.CTkFrame(self.left, fg_color="transparent")
        plot_area.pack(fill="both", expand=True, padx=12, pady=(2, 4))
        self.plot = tk.Canvas(plot_area, bg=FONDO_SPECTROGRAM, highlightthickness=0, height=500)
        self.plot.pack(fill="both", expand=True)
        self.plot.bind("<Configure>", lambda e: self.render_plot())
        self.plot.bind("<Button-1>", self.on_plot_click)
        self.info_row = ctk.CTkFrame(self.left, fg_color="transparent")
        self.info_row.pack(fill="x", padx=12, pady=(1, 4))
        self.star_hint = ctk.CTkLabel(self.info_row,
                                      text="★ favorite",
                                      text_color=("#806018", "#FCD34D"), font=self.app_font(10))
        self.star_hint.pack(side="left")
        self.validation_status_label = ctk.CTkLabel(
            self.info_row,
            text="Status: pending validation",
            text_color=("#475569", "#CBD5E1"),
            font=self.app_font(11, "bold")
        )
        self.validation_status_label.pack(side="right")

        # Reserve fixed space for Pending first; the summary cannot push it out.
        self.summary_frame = ctk.CTkFrame(self.left, corner_radius=10)
        self.summary_frame.pack(fill="x", padx=12, pady=(3, 8))
        self.pending_button = ctk.CTkButton(
            self.summary_frame, text="Pending →", width=110,
            command=self.goto_next_pending,
            fg_color=GRIS_NAVEGACION, hover_color=GRIS_NAVEGACION_HOVER,
            text_color="#FFFFFF",
            font=self.app_font(12, "bold"), height=32)
        self.pending_button.pack(side="right", padx=(5, 8), pady=5)
        self.summary_line = ctk.CTkLabel(
            self.summary_frame,
            text="SUMMARY | Total: 0 | Done: 0 | Pending: 0",
            anchor="w", font=self.app_font(11), text_color=("#20252A", "#E2E8F0"),
            width=1,
        )
        self.summary_line.pack(side="left", fill="x", expand=True, padx=(8, 0), pady=6)

        self.class_title = ctk.CTkLabel(self.right, text="classification", font=self.app_font(14, "bold"))
        self.class_title.grid(row=0, column=0, sticky="w", padx=18, pady=(8, 3))

        class_grid = ctk.CTkFrame(self.right, fg_color="transparent")
        class_grid.grid(row=1, column=0, sticky="ew", padx=14)
        class_grid.grid_columnconfigure((0, 1, 2), weight=1)
        positions = {
            "positive": (0, 0, 3),
            "negative": (1, 0, 3),
            "uncertain": (2, 0, 1),
            "reassigned": (2, 1, 1),
            "multitaxa": (2, 2, 1),
        }
        for code in CATEGORIES:
            info = CATEGORY_INFO[code]
            row, col, span = positions[code]
            btn = ctk.CTkButton(class_grid, text=info["label"], height=36,
                fg_color=info["color"], hover_color=info["hover"],
                text_color=info.get("text", "white"),
                font=self.app_font(15, "bold"), border_width=0,
                command=lambda c=code: self.set_category(c))
            btn.grid(row=row, column=col, columnspan=span, sticky="ew", padx=4, pady=3)
            self.category_buttons[code] = btn

        nav = ctk.CTkFrame(self.right, fg_color="transparent")
        nav.grid(row=2, column=0, sticky="ew", padx=14, pady=(6, 4))
        nav.grid_columnconfigure((0, 1), weight=1)
        nav.grid_columnconfigure(2, weight=0)
        self.undo_button = ctk.CTkButton(nav, text="↶ Undo", command=self.undo_classification,
            fg_color=GRIS_NAVEGACION, hover_color=GRIS_NAVEGACION_HOVER,
            text_color="#FFFFFF", font=self.app_font(14, "bold"), height=36)
        self.undo_button.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.skip_button = ctk.CTkButton(nav, text="➜ Skip", command=self.skip_segment,
            fg_color=GRIS_NAVEGACION, hover_color=GRIS_NAVEGACION_HOVER,
            text_color="#FFFFFF", font=self.app_font(14, "bold"), height=36)
        self.skip_button.grid(row=0, column=1, sticky="ew", padx=(6, 0))


        controls = ctk.CTkFrame(self.right, fg_color="transparent")
        controls.grid(row=3, column=0, sticky="ew", padx=14, pady=(4, 4))
        controls.grid_columnconfigure((0, 1, 2), weight=1)
        self.prev_button = ctk.CTkButton(controls, text="⬅", command=lambda: self.navigate(-1), height=42,
                                         fg_color=GRIS_NAVEGACION, hover_color=GRIS_NAVEGACION_HOVER,
            text_color="#FFFFFF",
                                         font=self.app_font(20, "bold"))
        self.prev_button.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.play_button = ctk.CTkButton(controls, text="Play", command=self.toggle_play, height=42,
                                         fg_color="#F0B8CC", hover_color="#E2A8BD",
            text_color="#FFFFFF",
                                         font=self.app_font(18, "bold"))
        self.play_button.grid(row=0, column=1, sticky="ew", padx=6)
        self.next_button = ctk.CTkButton(controls, text="➡", command=lambda: self.navigate(1), height=42,
                                         fg_color=GRIS_NAVEGACION, hover_color=GRIS_NAVEGACION_HOVER,
            text_color="#FFFFFF",
                                         font=self.app_font(20, "bold"))
        self.next_button.grid(row=0, column=2, sticky="ew", padx=(6, 0))

        self.autoplay_toggle = ctk.CTkCheckBox(self.right, text="Automatically play next segment",
            variable=self.autoplay_var, font=self.app_font(13))
        self.autoplay_toggle.grid(row=4, column=0, sticky="w", padx=18, pady=(0, 6))

        input_box = ctk.CTkFrame(self.right, corner_radius=10)
        input_box.grid(row=5, column=0, sticky="nsew", padx=14, pady=(2, 4))

        self.validated_label = ctk.CTkLabel(input_box, text="Validated scientific name:",
                                            font=self.app_font(14, "bold"))
        self.validated_label.pack(anchor="w", padx=12, pady=(10, 4))
        self.species_entry = ctk.CTkEntry(input_box, textvariable=self.species_var, font=self.app_font(14))
        self.species_entry.pack(fill="x", padx=12, pady=(0, 6))
        self.species_entry.configure(state="disabled")
        self.help_label = ctk.CTkLabel(input_box,
            text="Reassigned/Multitaxa: enter the name and press Enter; for Multitaxa, separate names with ;",
            text_color=("#506174", "#A9BBCD"), wraplength=480, justify="left", font=self.app_font(12))
        self.help_label.pack(anchor="w", padx=12, pady=(0, 8))
        self.comment_label = ctk.CTkLabel(input_box, text="Validation comment:",
                                           font=self.app_font(14, "bold"))
        self.comment_label.pack(anchor="w", padx=12, pady=(2, 4))
        self.comment_entry = ctk.CTkTextbox(input_box, height=65, wrap="word",
                                             font=(FUENTE_APP, 13))
        self.comment_entry.pack(fill="x", padx=12, pady=(0, 10))
        self.comment_entry.configure(state="disabled")

        save_area = ctk.CTkFrame(self.right, fg_color="transparent")
        save_area.grid(row=6, column=0, sticky="sew", padx=14, pady=(2, 8))
        self.export_button_bottom = ctk.CTkButton(save_area, text="Save CSV", width=150,
                                                  fg_color=AZUL_BOTONES, hover_color=AZUL_BOTONES_HOVER,
                                         text_color="#FFFFFF",
                                                  command=self.export_as, font=self.app_font(14, "bold"))
        self.export_button_bottom.pack(side="right", pady=(0, 4))

        bottom = ctk.CTkFrame(self.frame, fg_color="transparent")
        bottom.pack(fill="x", pady=(8, 0))
        self.progress_label = ctk.CTkLabel(bottom, textvariable=self.progress_var, font=self.app_font(13))
        self.progress_label.pack(side="left")
        self.status_label = ctk.CTkLabel(bottom, textvariable=self.status_var, text_color=("#506174", "#A9BBCD"), font=self.app_font(13))
        self.status_label.pack(side="right")

        self.species_entry.bind("<FocusOut>", lambda e: self.save())
        self.species_entry.bind("<Return>", self.confirm_scientific_name)
        self.comment_entry.bind("<FocusOut>", lambda e: self.save())
        self.name_entry.bind("<FocusOut>", lambda e: self.save())

    def update_summary(self):
        total = len(self.visible_indices) if self.visible_indices else (len(self.files) if self.files else 0)
        selected_label = self.species_filter_var.get() or ALL_SPECIES
        favorite_count = 0
        counts = {code: 0 for code in CATEGORIES}

        if self.files:
            target_indices = self.visible_indices
            for i in target_indices:
                key = str(self.files[i].relative_to(self.folder))
                row = self.rows.get(key, {})
                category = row.get("validationCategory", "")
                if category in counts:
                    counts[category] += 1
                if key in self.favorites:
                    favorite_count += 1
        classified = sum(counts.values())
        pending = max(0, total - classified)
        progress = (classified / total * 100) if total else 0.0

        line = (
            f"SUMMARY | Total: {total} | Done: {classified} | "
            f"Pending: {pending} | {progress:.1f}%"
        )
        self.summary_line.configure(text=line)

    def load_default_logo(self):
        base = Path(__file__).resolve().parent
        candidates = [base / self.logo_filename, base / "logo.png", base / "logo.jpg", base / "logo.jpeg"]
        for path in candidates:
            if path.exists():
                try:
                    self.set_logo(path)
                except Exception:
                    pass
                break

    def setup_app_icon(self):
        """Register the audita icon in the window and, when possible, the taskbar."""
        ico_path = Path(__file__).with_name("audita_icon.ico")
        png_path = Path(__file__).with_name("audita_icon.png")
        self._icon_images = []
        if sys.platform == "win32" and ico_path.is_file():
            try:
                self.root.iconbitmap(default=str(ico_path))
            except (OSError, tk.TclError):
                pass
        if png_path.is_file():
            try:
                image = Image.open(png_path).convert("RGBA")
                self._icon_images = [
                    ImageTk.PhotoImage(image.resize((size, size), Image.Resampling.LANCZOS))
                    for size in (256, 64, 48, 32, 16)
                ]
                self.root.iconphoto(True, *self._icon_images)
            except (OSError, tk.TclError, ValueError):
                pass

    def set_logo(self, path):
        im = Image.open(path).convert("RGBA")
        im.thumbnail((290, 115), Image.Resampling.LANCZOS)
        self.logo_photo = ctk.CTkImage(light_image=im, dark_image=im, size=im.size)
        self.logo_area.configure(text="", image=self.logo_photo)

    def update_validated_field(self):
        enabled = self.validator_ready() and self.category_var.get() in ("reassigned", "multitaxa")
        self.species_entry.configure(state="normal" if enabled else "disabled")
        if not enabled:
            self.species_var.set("")

    def set_category(self, code):
        if not self.files or not self.validator_ready():
            return
        key = self.current_key()
        old = self.rows.get(key)
        self.history.append((self.index, key, old.copy() if old is not None else None))
        self.category_var.set(code)
        self.refresh_category_buttons()
        self.update_validated_field()
        self.update_validation_status()
        if code in ("reassigned", "multitaxa"):
            self.species_entry.focus_set()
            return
        self.save()
        self.advance_after_classification()

    def confirm_scientific_name(self, event=None):
        if self.category_var.get() in ("reassigned", "multitaxa"):
            if not self.species_var.get().strip():
                messagebox.showwarning("Name required", "Enter the scientific name before continuing.")
                return
            self.save()
            self.advance_after_classification()
        else:
            self.save()
        self.root.focus_set()

    def _pending_indices(self):
        """Unclassified audio indices in the currently selected species filter."""
        return [
            i for i in self.visible_indices
            if self.rows.get(str(self.files[i].relative_to(self.folder)), {}).get("validationCategory") not in CATEGORIES
        ]

    def _is_folder_completed(self):
        return bool(self.files) and all(
            self.rows.get(str(path.relative_to(self.folder)), {}).get("validationCategory") in CATEGORIES
            for path in self.files
        )

    def _notify_completion(self):
        if not self.completion_notified:
            self.completion_notified = True
            self.stop()
            messagebox.showinfo("Validation completed", "All segments in this folder have been validated.")

    def goto_next_pending(self):
        """Find the next unclassified segment in the current filter."""
        if not self.files or not self.validator_ready():
            return
        self.save()
        pending = self._pending_indices()
        if not pending:
            if self._is_folder_completed():
                self._notify_completion()
            else:
                messagebox.showinfo("No pending segments", "All segments in the current filter have been validated.")
            return
        # Uses confidence-sorted positions rather than numeric file indices.
        positions = self.visible_indices
        cur_pos = positions.index(self.index) if self.index in positions else -1
        pending_after = [i for i in pending if positions.index(i) > cur_pos]
        self.index = pending_after[0] if pending_after else pending[0]
        self.load_current()
        if self.autoplay_var.get():
            self.toggle_play()

    def notify_if_completed(self, was_incomplete):
        if was_incomplete and self._is_folder_completed():
            self._notify_completion()

    def advance_after_classification(self):
        if not self.files or not self.validator_ready():
            return
        if self._is_folder_completed():
            self._notify_completion()
            return
        pending = self._pending_indices()
        if not pending:
            self.stop()
            messagebox.showinfo("No pending segments", "There are no pending segments in the selected species filter.")
            return
        positions = self.visible_indices
        cur_pos = positions.index(self.index) if self.index in positions else -1
        pending_after = [i for i in pending if positions.index(i) > cur_pos]
        self.index = pending_after[0] if pending_after else pending[0]
        self.load_current()
        if self.autoplay_var.get():
            self.toggle_play()

    def skip_segment(self):
        self.advance_after_classification()

    def undo_classification(self):
        if not self.validator_ready() or not self.history or not self.files:
            return
        self.stop()
        idx, key, old = self.history.pop()
        if old is None:
            self.rows.pop(key, None)
        else:
            self.rows[key] = old
        self.write_csv(self.csv_path)
        self.completion_notified = False
        self.index = idx
        self.load_current()


    def refresh_category_buttons(self):
        selected = self.category_var.get()
        for code, button in self.category_buttons.items():
            info = CATEGORY_INFO[code]
            if code == selected:
                button.configure(border_width=3, border_color="white", fg_color=info["hover"])
            else:
                button.configure(border_width=0, fg_color=info["color"])

    def update_validation_status(self):
        """Show whether the current segment is pending or already validated."""
        if not getattr(self, "files", None):
            self.validation_status_label.configure(text="Status: pending validation", text_color=("#475569", "#CBD5E1"))
            return
        key = self.current_key()
        saved_category = self.rows.get(key, {}).get("validationCategory", "")
        current_category = self.category_var.get()

        if current_category in CATEGORIES:
            label = CATEGORY_INFO[current_category]["label"]
            if current_category != saved_category:
                if current_category in ("reassigned", "multitaxa"):
                    text = f"Status: {label} selected · press Enter to validate"
                else:
                    text = f"Status: {label} selected"
                color = ("#7C2D12", "#FCD34D")
            else:
                text = f"Status: validated as {label}"
                color = ("#14532D", "#86EFAC")
        else:
            text = "Status: pending validation"
            color = ("#475569", "#CBD5E1")

        self.validation_status_label.configure(text=text, text_color=color)

    def on_plot_click(self, event):
        if self.validator_ready() and event.x >= self.plot.winfo_width() - 68 and event.y <= 58:
            if self.files:
                self.favorite_var.set(not self.favorite_var.get())
                key = self.current_key()
                if self.favorite_var.get():
                    self.favorites.add(key)
                else:
                    self.favorites.discard(key)
                self.write_favorites()
                self.write_csv(self.csv_path)
                self.update_summary()
                self.draw_star()

    def draw_star(self):
        self.plot.delete("favorite_star")
        w = self.plot.winfo_width()
        if w < 90:
            return
        active = self.favorite_var.get()
        self.plot.create_text(
            w - 30, 30,
            text="★" if active else "☆",
            font=(FUENTE_EJES, 30, "bold"),
            fill=COLOR_ESTRELLA if active else "#f8fafc",
            tags="favorite_star",
        )

    def draw_playhead(self, seconds=0.0):
        self.plot.delete("playhead")
        if self.audio is None or not self.sr:
            return
        duration = len(self.audio) / self.sr
        if duration <= 0:
            return
        w = self.plot.winfo_width()
        h = self.plot.winfo_height()
        # Must match the plot geometry from render_plot exactly.
        left_margin, top_margin = 58, 18
        right_margin, bottom_margin = 18, 66
        pw = max(1, w - left_margin - right_margin)
        ph = max(1, h - top_margin - bottom_margin)
        x = left_margin + pw * min(1.0, max(0.0, seconds / duration))
        self.plot.create_line(x, top_margin, x, top_margin + ph,
                              fill=COLOR_LINEA_REPRODUCCION, width=3, tags="playhead")

    def _find_pil_font(self, size):
        candidates = []
        family = FUENTE_EJES.lower()
        common = {
            "arial": ["arial.ttf", "Arial.ttf"],
            "verdana": ["verdana.ttf", "Verdana.ttf"],
            "tahoma": ["tahoma.ttf", "Tahoma.ttf"],
            "calibri": ["calibri.ttf", "Calibri.ttf"],
            "segoe ui": ["segoeui.ttf", "SegoeUI.ttf"],
            "times new roman": ["times.ttf", "Times New Roman.ttf", "timesnewroman.ttf"],
            "georgia": ["georgia.ttf", "Georgia.ttf"],
            "courier new": ["cour.ttf", "Courier New.ttf"],
            "helvetica": ["Helvetica.ttf", "helvetica.ttf"],
        }
        candidates.extend(common.get(family, []))
        candidates.extend(["DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"])
        for cand in candidates:
            try:
                return ImageFont.truetype(cand, size=size)
            except Exception:
                continue
        return ImageFont.load_default()

    def open_folder(self):
        if not self.validator_ready():
            return
        selected = filedialog.askdirectory(title="Select folder containing audio files")
        if not selected:
            return
        self.stop()
        self.folder = Path(selected)
        self.completion_notified = False
        self.files = sorted(
            (p for p in self.folder.rglob("*") if p.is_file() and p.suffix.lower() in AUDIO_EXT),
            key=confidence_sort_key,
        )
        if not self.files:
            messagebox.showwarning("No audio files", "No WAV, FLAC, or OGG files were found.")
            return
        self.csv_path = self.folder / "validaciones.csv"
        self.rows = {}
        self.favorites_path = self.folder / ".audita_favorites.txt"
        self.favorites = set(self.favorites_path.read_text(encoding="utf-8").splitlines()) if self.favorites_path.exists() else set()
        if self.csv_path.exists():
            with open(self.csv_path, newline="", encoding="utf-8-sig") as handle:
                for row in csv.DictReader(handle):
                    key = row.get("fileName") or row.get("filename")
                    if not key:
                        continue
                    self.rows[key] = {
                        "observationID": row.get("observationID") or row.get("ObservationID", ""),
                        "mediaID": (extract_metadata(Path(key).name)[0] + Path(key).suffix)
                        if Path(key).suffix else row.get("mediaID") or row.get("MediaID", ""),
                        "classifiedBy": row.get("classifiedBy") or row.get("validator", ""),
                        "scientificNameProposed": row.get("scientificNameProposed", ""),
                        "validationCategory": row.get("validationCategory") or row.get("category", ""),
                        "scientificNameValidated": row.get("scientificNameValidated", ""),
                        "fileName": key,
                        "validationComment": row.get("validationComment", ""),
                        "favorite": "true" if str(row.get("favorite", "")).lower() in ("true", "1", "yes") else "false",
                    }
                    if "favorite" in row:
                        if self.rows[key]["favorite"] == "true":
                            self.favorites.add(key)
                        else:
                            self.favorites.discard(key)
            with open(self.csv_path, encoding="utf-8-sig", newline="") as handle:
                old_cols = next(csv.reader(handle), [])
            if old_cols != COLUMNS:
                import shutil
                backup = self.folder / "validaciones_formato_anterior.csv"
                if not backup.exists():
                    shutil.copy2(self.csv_path, backup)
        self.write_favorites()
        self.species_by_file = {str(p.relative_to(self.folder)): detected_species(self.folder, p) for p in self.files}
        species = sorted({name for name in self.species_by_file.values() if name})
        if any(not name for name in self.species_by_file.values()):
            species.append(UNKNOWN_SPECIES)
        self.species_combo.configure(values=[ALL_SPECIES] + species)
        self.species_filter_var.set(ALL_SPECIES)
        self.index = 0
        self.update_segment_list()
        self.load_current()

    def update_segment_list(self):
        selected = self.species_filter_var.get()
        self.visible_indices = [
            i for i, path in enumerate(self.files)
            if selected == ALL_SPECIES or (self.species_by_file[str(path.relative_to(self.folder))] or UNKNOWN_SPECIES) == selected
        ]
        values = [str(self.files[i].relative_to(self.folder)) for i in self.visible_indices]
        self.combo.configure(values=values)

    def filter_species(self, event=None):
        if not self.files:
            return
        self.save()
        self.update_segment_list()
        if self.visible_indices:
            if self.index not in self.visible_indices:
                self.index = self.visible_indices[0]
            self.load_current()
        else:
            self.validation_status_label.configure(text="Status: no segments in this filter", text_color=("#475569", "#CBD5E1"))
            self.update_summary()

    def select_from_menu(self, event=None):
        position = self.visible_indices.index(self.index) if self.index in self.visible_indices else -1
        value = self.file_var.get()
        values = [str(self.files[i].relative_to(self.folder)) for i in self.visible_indices]
        if value in values:
            position = values.index(value)
        if 0 <= position < len(self.visible_indices):
            self.save()
            self.index = self.visible_indices[position]
            self.load_current()

    def current_key(self):
        return str(self.files[self.index].relative_to(self.folder))

    def load_current(self):
        if not self.files:
            return
        self.stop()
        path = self.files[self.index]
        key = self.current_key()
        self.file_var.set(key)
        row = self.rows.get(key, {})
        self.category_var.set(row.get("validationCategory", ""))
        self.refresh_category_buttons()
        self.species_entry.configure(state="normal")
        self.species_var.set(row.get("scientificNameValidated", ""))
        self.update_validated_field()
        self.comment_entry.configure(state="normal")
        self.comment_entry.delete("1.0", "end")
        self.comment_entry.insert("1.0", row.get("validationComment", ""))
        self.comment_entry.configure(state="normal" if self.validator_ready() else "disabled")
        self.favorite_var.set(key in self.favorites)
        self.update_validation_status()
        media, start, end = extract_metadata(path.name)
        media = f"{media}{path.suffix}"
        proposal = self.species_by_file.get(key, "")
        self.meta_var.set(
            f"Proposed species: {proposal or 'unavailable'}     |     mediaID: {media}     |     Interval: {start or 'sin datos'}–{end or 'sin datos'} s"
        )
        try:
            y, rate = sf.read(path, dtype="float32", always_2d=True)
            self.audio = y.mean(axis=1)
            self.sr = rate
            self.status_var.set(f"{len(self.audio)/rate:.2f} s · {rate:,} Hz")
        except Exception as exc:
            self.audio = self.sr = None
            self.status_var.set(f"Error de audio: {exc}")
        self.render_plot()
        self.draw_star()
        self.draw_playhead()
        count = sum(
            1 for k in [str(p.relative_to(self.folder)) for p in self.files]
            if self.rows.get(k, {}).get("validationCategory") in CATEGORIES
        )
        self.progress_var.set(
            f"{self.index + 1} / {len(self.files)}  |  {count} classified  |  ★ {len(self.favorites)} favorites"
        )
        self.update_summary()

    def render_plot(self):
        self.plot.delete("all")
        w = self.plot.winfo_width()
        h = self.plot.winfo_height()
        if w < 80 or h < 80:
            return
        if self.audio is None or len(self.audio) < 32:
            self.plot.create_text(w // 2, h // 2, text="Open an audio file to view its spectrogram", fill="white")
            return
        try:
            nperseg = min(1024, len(self.audio))
            f, t, s = spectrogram(self.audio, fs=self.sr, nperseg=nperseg, noverlap=nperseg * 3 // 4)
            keep = f <= min(self.sr / 2, 12000)
            s = s[keep]
            s = s[:, ::max(1, s.shape[1] // max(w, 420))]
            db = 10 * np.log10(s + 1e-12)
            hi = np.percentile(db, 99)
            norm = np.clip((db - (hi - 75)) / 75, 0, 1)
            rgb = magma_colors(norm)
            image = Image.fromarray(np.flipud(rgb), mode="RGB")

            left_margin, top_margin = 58, 18
            right_margin, bottom_margin = 18, 66
            pw = max(1, w - left_margin - right_margin)
            ph = max(1, h - top_margin - bottom_margin)
            image = image.resize((pw, ph), Image.Resampling.BILINEAR)
            final = Image.new("RGB", (w, h), FONDO_SPECTROGRAM)
            final.paste(image, (left_margin, top_margin))
            d = ImageDraw.Draw(final)
            axis_font = self._find_pil_font(self.axis_font_size)
            tick_font = self._find_pil_font(max(18, self.axis_font_size - 2))
            fmax = min(self.sr / 2, 12000)

            # Outer box
            d.rectangle((left_margin, top_margin, left_margin + pw, top_margin + ph), outline="#1f2937", width=1)

            for frac in (0, 0.25, 0.5, 0.75, 1.0):
                fy = top_margin + int((1 - frac) * ph)
                label = f"{frac * fmax / 1000:.1f}"
                d.line(((left_margin - 6, fy), (left_margin, fy)), fill="#E5E7EB", width=2)
                d.text((4, fy - self.axis_font_size // 2 - 1), label, fill="#F8FAFC", font=tick_font)

                fx = left_margin + int(frac * pw)
                time_label = f"{frac * len(self.audio) / self.sr:.1f}"
                d.line(((fx, top_margin + ph), (fx, top_margin + ph + 7)), fill="#E5E7EB", width=2)
                tw = d.textbbox((0, 0), time_label, font=tick_font)
                text_w = tw[2] - tw[0]
                d.text((fx - text_w / 2, top_margin + ph + 14), time_label, fill="#F8FAFC", font=tick_font)

            # Axis titles inside margins, larger like example
            d.text((4, 2), "Frequency (kHz)", fill="#FFFFFF", font=axis_font)
            x_title = "Time (s)"
            tb = d.textbbox((0, 0), x_title, font=axis_font)
            tx = left_margin + (pw - (tb[2] - tb[0])) / 2
            d.text((tx, h - self.axis_font_size - 6), x_title, fill="#FFFFFF", font=axis_font)

            self.photo = ImageTk.PhotoImage(final)
            self.plot.create_image(0, 0, image=self.photo, anchor="nw")
            self.draw_star()
            if self.playing:
                self.draw_playhead(time.monotonic() - self.playback_start)
            else:
                self.draw_playhead(0)
        except Exception as exc:
            self.plot.create_text(w // 2, h // 2, text=f"Could not render spectrogram: {exc}", fill="white")

    def toggle_play(self, event=None):
        if event is not None and isinstance(event.widget, (tk.Entry, tk.Text)):
            return
        if not self.validator_ready():
            return
        if self.playing:
            self.stop()
            return
        if self.audio is None or self.sr is None:
            return
        if sd is None:
            messagebox.showerror("Audio", "Install sounddevice: pip install sounddevice")
            return
        try:
            self.stop()
            sd.play(self.audio, samplerate=self.sr, blocking=False)
            self.playback_start = time.monotonic()
            self.playing = True
            self.play_button.configure(text="■ Stop")
            self.check_playback()
        except Exception as exc:
            self.stop()
            messagebox.showerror("Playback", str(exc))

    def check_playback(self):
        self.playback_job = None
        if not self.playing:
            return
        elapsed = time.monotonic() - self.playback_start
        duration = len(self.audio) / self.sr
        self.draw_playhead(min(elapsed, duration))
        if elapsed >= duration:
            self.stop(reset_line=False)
            return
        self.playback_job = self.root.after(35, self.check_playback)

    def stop(self, reset_line=True):
        if self.playback_job is not None:
            self.root.after_cancel(self.playback_job)
            self.playback_job = None
        if sd is not None:
            sd.stop()
        self.playing = False
        self.play_button.configure(text="▶ Play")
        if reset_line:
            self.draw_playhead(0)

    def category_changed(self):
        self.save()
        if self.category_var.get() in ("reassigned", "multitaxa"):
            self.species_entry.focus_set()

    def write_favorites(self):
        if self.folder:
            self.favorites_path.write_text(
                "\n".join(sorted(self.favorites)) + ("\n" if self.favorites else ""),
                encoding="utf-8",
            )

    def save(self):
        if not self.files or not self.validator_ready():
            return
        key = self.current_key()
        category = self.category_var.get()
        scientific = self.species_var.get().strip()
        comment = self.comment_entry.get("1.0", "end-1c").strip()
        if category not in CATEGORIES:
            return
        if category in ("reassigned", "multitaxa") and not scientific:
            return
        media, _, _ = extract_metadata(self.files[self.index].name)
        was_incomplete = any(
            self.rows.get(str(path.relative_to(self.folder)), {}).get("validationCategory") not in CATEGORIES
            for path in self.files
        )
        self.rows[key] = {
            "observationID": observation_id(self.files[self.index].name),
            "mediaID": f"{media}{self.files[self.index].suffix}",
            "classifiedBy": self.name_var.get().strip(),
            "scientificNameProposed": self.species_by_file.get(key, ""),
            "validationCategory": category,
            "scientificNameValidated": scientific if category in ("reassigned", "multitaxa") else "",
            "fileName": key,
            "validationComment": comment,
            "favorite": "true" if key in self.favorites else "false",
        }
        self.write_csv(self.csv_path)
        self.update_summary()
        self.update_validation_status()
        self.notify_if_completed(was_incomplete)

    def write_csv(self, path):
        try:
            temp = Path(str(path) + ".tmp")
            with open(temp, "w", newline="", encoding="utf-8-sig") as file:
                writer = csv.DictWriter(file, fieldnames=COLUMNS, extrasaction="ignore")
                writer.writeheader()
                # Export every classified segment, plus favorite-only segments.
                keys = set(self.rows) | self.favorites
                for key in sorted(keys):
                    row = dict(self.rows.get(key, {}))
                    if not row and self.folder:
                        audio_path = self.folder / key
                        media, _, _ = extract_metadata(audio_path.name)
                        row = {
                            "observationID": observation_id(audio_path.name),
                            "mediaID": f"{media}{audio_path.suffix}",
                            "classifiedBy": self.name_var.get().strip(),
                            "scientificNameProposed": self.species_by_file.get(key, ""),
                            "validationCategory": "",
                            "scientificNameValidated": "",
                            "fileName": key,
                            "validationComment": "",
                        }
                    row["favorite"] = "true" if key in self.favorites else "false"
                    writer.writerow(row)
            os.replace(temp, path)
        except OSError as exc:
            messagebox.showerror("Error saving CSV", str(exc))

    def export_as(self):
        if not self.validator_ready() or not self.files:
            messagebox.showinfo("No folder selected", "Select a folder first")
            return
        self.save()
        destination = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")], initialfile="validaciones.csv")
        if destination:
            self.write_csv(Path(destination))
            self.status_var.set(f"CSV exported: {destination}")

    def navigate(self, delta):
        if not self.files:
            return
        self.save()
        indices = self.visible_indices or list(range(len(self.files)))
        try:
            position = indices.index(self.index)
        except ValueError:
            position = 0
        self.index = indices[(position + delta) % len(indices)]
        self.load_current()

    def close(self):
        self.save()
        self.stop()
        self.root.destroy()


if __name__ == "__main__":
    # Set before constructing Tk to prevent taskbar grouping under python.exe.
    if sys.platform == "win32":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "audita.SegmentValidation.Desktop.1"
            )
        except (AttributeError, OSError):
            pass
    root = ctk.CTk()
    ValidatorApp(root)
    root.mainloop()
