import asyncio
import json
import os
import platform
import queue
import threading
import time
import tkinter as tk
from tkinter import filedialog
from tkinter import messagebox
from tkinter import ttk

from answerer import generate_answer, looks_like_question
from knowledge_base import (
    DEFAULT_EMBEDDING_MODEL,
    add_text_file,
    clear_knowledge,
    knowledge_stats,
    load_knowledge,
    rebuild_embeddings,
    retrieve_context,
)
from translator import (
    capture_and_translate,
    list_audio_apps,
    list_audio_windows,
    list_input_devices,
    list_system_audio_devices,
)


BG = "#111111"
SURFACE = "#1b1b1b"
SURFACE_ALT = "#242424"
TEXT = "#f5f2ea"
MUTED = "#aaa59a"
LINE = "#34312b"
EN = "#6bb7ff"
RU = "#7bd88f"
WARN = "#ffca66"
ERROR = "#ff6b6b"
MIN_WIDTH = 1120
MIN_HEIGHT = 620
TURN_FINALIZE_MS = 1400
SETTINGS_PATH = os.path.join(os.path.dirname(__file__), "settings.json")
IS_MACOS = platform.system() == "Darwin"
IS_WINDOWS = platform.system() == "Windows"
LANGUAGES = {
    "en": {"short": "EN", "name": "English", "speech": "English speech", "translation": "English translation"},
    "ru": {"short": "RU", "name": "Русский", "speech": "Русская речь", "translation": "Русский перевод"},
    "hy": {"short": "HY", "name": "Հայերեն", "speech": "Հայերեն speech", "translation": "Հայերեն перевод"},
    "es": {"short": "ES", "name": "Español", "speech": "Spanish speech", "translation": "Spanish translation"},
    "de": {"short": "DE", "name": "Deutsch", "speech": "German speech", "translation": "German translation"},
    "fr": {"short": "FR", "name": "Français", "speech": "French speech", "translation": "French translation"},
    "it": {"short": "IT", "name": "Italiano", "speech": "Italian speech", "translation": "Italian translation"},
    "pt": {"short": "PT", "name": "Português", "speech": "Portuguese speech", "translation": "Portuguese translation"},
    "tr": {"short": "TR", "name": "Türkçe", "speech": "Turkish speech", "translation": "Turkish translation"},
}
DEFAULT_SETTINGS = {
    "api_key": "",
    "model": "gemini-3.5-live-translate-preview",
    "target_language_code": "ru",
    "echo_target_language": False,
    "answer_enabled": False,
    "answer_model": "gemini-2.5-flash",
    "answer_language": "ru",
    "answer_prompt": (
        "Answer naturally and confidently. Keep it concise. "
        "For interview questions, use first person and give a practical example when possible."
    ),
    "rag_enabled": True,
    "embedding_model": DEFAULT_EMBEDDING_MODEL,
    "rag_min_similarity": 0.42,
    "rag_top_k": 5,
    "transcript_mode": "interview",
}


def load_local_env():
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if not os.path.exists(env_path):
        return
    with open(env_path, "r", encoding="utf-8") as env_file:
        for line in env_file:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def load_settings():
    settings = DEFAULT_SETTINGS.copy()
    if os.path.exists(SETTINGS_PATH):
        try:
            with open(SETTINGS_PATH, "r", encoding="utf-8") as settings_file:
                saved = json.load(settings_file)
            if isinstance(saved, dict):
                settings.update({key: saved.get(key, value) for key, value in settings.items()})
        except (OSError, json.JSONDecodeError):
            pass
    if not settings["api_key"]:
        settings["api_key"] = os.getenv("GOOGLE_API_KEY", "")
    return settings


def save_settings(settings):
    with open(SETTINGS_PATH, "w", encoding="utf-8") as settings_file:
        json.dump(settings, settings_file, indent=2, ensure_ascii=False)


def merge_text(old, new):
    old = old.strip()
    new = new.strip()
    if not old:
        return new
    if not new or new in old:
        return old
    if old in new:
        return new
    return f"{old} {new}"


def language_info(code):
    code = (code or "").lower()
    return LANGUAGES.get(
        code,
        {
            "short": code.upper() or "??",
            "name": code or "Unknown",
            "speech": f"{code.upper()} speech" if code else "Speech",
            "translation": f"{code.upper()} translation" if code else "Translation",
        },
    )


class FlatButton(tk.Frame):
    def __init__(
        self,
        parent,
        text,
        command,
        bg=SURFACE_ALT,
        fg=TEXT,
        active_bg=LINE,
        disabled_bg="#2c2c2c",
        disabled_fg="#77736b",
        font=("SF Pro Text", 12, "bold"),
        padx=14,
        pady=8,
    ):
        super().__init__(parent, bg=bg, highlightthickness=1, highlightbackground=LINE)
        self.command = command
        self.normal_bg = bg
        self.normal_fg = fg
        self.active_bg = active_bg
        self.disabled_bg = disabled_bg
        self.disabled_fg = disabled_fg
        self.state = "normal"
        self.label = tk.Label(
            self,
            text=text,
            bg=bg,
            fg=fg,
            font=font,
            padx=padx,
            pady=pady,
        )
        self.label.pack(fill="both", expand=True)
        for widget in (self, self.label):
            widget.bind("<Button-1>", self._click)
            widget.bind("<Enter>", self._enter)
            widget.bind("<Leave>", self._leave)

    def _click(self, _event):
        if self.state != "disabled" and self.command:
            self.command()

    def _enter(self, _event):
        if self.state != "disabled":
            self._set_colors(self.active_bg, self.normal_fg)

    def _leave(self, _event):
        if self.state != "disabled":
            self._set_colors(self.normal_bg, self.normal_fg)

    def _set_colors(self, bg, fg):
        super().configure(bg=bg)
        self.label.configure(bg=bg, fg=fg)

    def configure(self, cnf=None, **kwargs):
        if cnf:
            kwargs.update(cnf)
        if "state" in kwargs:
            self.state = kwargs.pop("state")
            if self.state == "disabled":
                self._set_colors(self.disabled_bg, self.disabled_fg)
            else:
                self._set_colors(self.normal_bg, self.normal_fg)
        if "text" in kwargs:
            self.label.configure(text=kwargs.pop("text"))
        if kwargs:
            super().configure(**kwargs)

    config = configure


class TranscriptRow:
    def __init__(self, parent, timestamp, source_info, target_info, english="", russian=""):
        self.frame = tk.Frame(parent, bg=BG)
        self.frame.grid_columnconfigure(0, weight=1, uniform="columns")
        self.frame.grid_columnconfigure(1, weight=1, uniform="columns")

        self.english = english
        self.russian = russian
        self.answer = ""
        self.answer_after_id = None
        self.answer_requested_text = ""
        self.finalize_after_id = None
        self.finalized = False
        self.timestamp = timestamp

        self.en_box = self._make_cell(0, source_info["short"], source_info["speech"], EN)
        self.ru_box = self._make_cell(1, target_info["short"], target_info["translation"], RU)
        self.answer_outer, self.answer_box = self._make_answer_cell()
        self.time_label = tk.Label(
            self.frame,
            text=f"{timestamp} - Live",
            bg=BG,
            fg=WARN,
            font=("SF Pro Text", 10),
            anchor="e",
        )
        self.time_label.grid(row=2, column=0, columnspan=2, sticky="ew", padx=8, pady=(2, 10))
        self.set_english(english)
        self.set_russian(russian)
        self.set_answer("")

    def _make_cell(self, column, short_label, full_label, color):
        outer = tk.Frame(self.frame, bg=SURFACE, highlightbackground=LINE, highlightthickness=1)
        outer.grid(row=0, column=column, sticky="nsew", padx=8, pady=(6, 0))
        outer.grid_columnconfigure(0, weight=1)

        top = tk.Frame(outer, bg=SURFACE)
        top.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 4))

        badge = tk.Label(
            top,
            text=short_label,
            bg=color,
            fg="#101010",
            font=("SF Pro Text", 10, "bold"),
            padx=7,
            pady=2,
        )
        badge.pack(side="left")

        title = tk.Label(
            top,
            text=full_label,
            bg=SURFACE,
            fg=MUTED,
            font=("SF Pro Text", 11),
            padx=8,
        )
        title.pack(side="left")

        text = tk.Label(
            outer,
            text="",
            bg=SURFACE,
            fg=TEXT,
            font=("SF Pro Text", 16),
            justify="left",
            anchor="nw",
            wraplength=340,
            padx=12,
            pady=10,
        )
        text.grid(row=1, column=0, sticky="nsew")
        return text

    def _make_answer_cell(self):
        outer = tk.Frame(self.frame, bg="#181818", highlightbackground=LINE, highlightthickness=1)
        outer.grid(row=1, column=0, columnspan=2, sticky="ew", padx=8, pady=(8, 0))
        outer.grid_columnconfigure(0, weight=1)

        top = tk.Frame(outer, bg="#181818")
        top.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 0))

        badge = tk.Label(
            top,
            text="AI",
            bg=WARN,
            fg="#101010",
            font=("SF Pro Text", 10, "bold"),
            padx=7,
            pady=2,
        )
        badge.pack(side="left")

        title = tk.Label(
            top,
            text="Answer",
            bg="#181818",
            fg=MUTED,
            font=("SF Pro Text", 11),
            padx=8,
        )
        title.pack(side="left")

        text = tk.Label(
            outer,
            text="",
            bg="#181818",
            fg=TEXT,
            font=("SF Pro Text", 14),
            justify="left",
            anchor="nw",
            wraplength=720,
            padx=12,
            pady=10,
        )
        text.grid(row=1, column=0, sticky="ew")
        return outer, text

    def set_english(self, text):
        self.english = text
        self.en_box.configure(text=text or "...")

    def set_russian(self, text):
        self.russian = text
        self.ru_box.configure(text=text or "...")

    def set_answer(self, text):
        self.answer = text
        if text:
            self.answer_box.configure(text=text)
            if not self.answer_outer.winfo_ismapped():
                self.answer_outer.grid()
        else:
            self.answer_box.configure(text="")
            self.answer_outer.grid_remove()

    def set_finalized(self, finalized):
        self.finalized = finalized
        state = "Final" if finalized else "Live"
        color = MUTED if finalized else WARN
        self.time_label.configure(text=f"{self.timestamp} - {state}", fg=color)

    def set_wraplength(self, width):
        wrap = max(220, int((width - 72) / 2))
        self.en_box.configure(wraplength=wrap)
        self.ru_box.configure(wraplength=wrap)
        self.answer_box.configure(wraplength=max(320, width - 72))


class GemTranslateApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Gem Translate")
        self.root.geometry("1180x680")
        self.root.minsize(MIN_WIDTH, MIN_HEIGHT)
        self.root.configure(bg=BG)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

        self.events = queue.Queue()
        self.rows = []
        self.current_row = None
        self.worker = None
        self.stop_flag = threading.Event()
        self.last_level = 0
        self.started_at = None
        self.devices = []
        self.device_values = {}
        self.windows = []
        self.window_values = {}
        self.apps = []
        self.app_values = {}
        self.system_audio_devices = []
        self.system_audio_values = {}
        self.settings = load_settings()
        self.settings_window = None
        self.knowledge_window = None
        self.prompt_window = None
        self.answer_var = tk.BooleanVar(value=bool(self.settings["answer_enabled"]))
        self.rag_var = tk.BooleanVar(value=bool(self.settings["rag_enabled"]))
        self.transcript_scroll_active = False

        self._build_ui()
        self.refresh_devices()
        self.root.after(80, self.poll_events)
        self.root.after(400, self.tick)

    def _build_ui(self):
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(1, weight=1)

        toolbar = tk.Frame(self.root, bg=BG)
        toolbar.grid(row=0, column=0, sticky="ew", padx=18, pady=(16, 12))
        toolbar.grid_columnconfigure(0, weight=1)

        top_line = tk.Frame(toolbar, bg=BG)
        top_line.grid(row=0, column=0, sticky="ew")
        top_line.grid_columnconfigure(1, weight=1)

        title_block = tk.Frame(top_line, bg=BG)
        title_block.grid(row=0, column=0, sticky="w")

        tk.Label(
            title_block,
            text="Gem Translate",
            bg=BG,
            fg=TEXT,
            font=("SF Pro Display", 20, "bold"),
        ).pack(anchor="w")
        self.direction_label = tk.Label(
            title_block,
            text="",
            bg=BG,
            fg=MUTED,
            font=("SF Pro Text", 11),
        )
        self.direction_label.pack(anchor="w")
        self.config_label = tk.Label(
            title_block,
            text="",
            bg=BG,
            fg=MUTED,
            font=("SF Pro Text", 10),
        )
        self.config_label.pack(anchor="w")

        self.status_label = tk.Label(
            top_line,
            text="Ready",
            bg=SURFACE_ALT,
            fg=TEXT,
            font=("SF Pro Text", 12, "bold"),
            padx=12,
            pady=7,
        )
        self.status_label.grid(row=0, column=1, padx=(18, 12), sticky="w")

        actions = tk.Frame(top_line, bg=BG)
        actions.grid(row=0, column=2, sticky="e")

        self.pin_var = tk.BooleanVar(value=True)
        self.pin_button = tk.Checkbutton(
            actions,
            text="Top",
            variable=self.pin_var,
            command=self.apply_topmost,
            bg=BG,
            fg=TEXT,
            selectcolor=SURFACE,
            activebackground=BG,
            activeforeground=TEXT,
            font=("SF Pro Text", 12),
        )
        self.pin_button.grid(row=0, column=0, padx=(0, 10))

        self.start_button = FlatButton(
            actions,
            text="Start",
            command=self.start,
            bg=RU,
            fg="#101010",
            active_bg="#95e9a5",
            disabled_bg="#36533d",
            disabled_fg="#8bbd95",
            padx=20,
        )
        self.start_button.grid(row=0, column=1, padx=(0, 8), sticky="ew")

        self.stop_button = FlatButton(
            actions,
            text="Stop",
            command=self.stop,
            bg=ERROR,
            fg="#101010",
            active_bg="#ff8a8a",
            disabled_bg="#332224",
            disabled_fg="#8b6468",
            padx=20,
        )
        self.stop_button.grid(row=0, column=2, padx=(0, 8), sticky="ew")
        self.stop_button.configure(state="disabled")

        self.clear_button = FlatButton(
            actions,
            text="Clear",
            command=self.clear,
            bg=SURFACE_ALT,
            fg=TEXT,
            active_bg=LINE,
            font=("SF Pro Text", 12),
        )
        self.clear_button.grid(row=0, column=3, padx=(0, 8), sticky="ew")

        self.knowledge_button = FlatButton(
            actions,
            text="Knowledge",
            command=self.open_knowledge,
            bg=SURFACE_ALT,
            fg=TEXT,
            active_bg=LINE,
            font=("SF Pro Text", 12),
        )
        self.knowledge_button.grid(row=0, column=4, padx=(0, 8), sticky="ew")

        self.prompt_button = FlatButton(
            actions,
            text="Prompt",
            command=self.open_prompt,
            bg=SURFACE_ALT,
            fg=TEXT,
            active_bg=LINE,
            font=("SF Pro Text", 12),
        )
        self.prompt_button.grid(row=0, column=5, padx=(0, 8), sticky="ew")

        self.settings_button = FlatButton(
            actions,
            text="Settings",
            command=self.open_settings,
            bg=SURFACE_ALT,
            fg=TEXT,
            active_bg=LINE,
            font=("SF Pro Text", 12),
        )
        self.settings_button.grid(row=0, column=6, sticky="ew")

        controls = tk.Frame(toolbar, bg=SURFACE, highlightbackground=LINE, highlightthickness=1)
        controls.grid(row=1, column=0, sticky="ew", pady=(14, 0))
        controls.grid_columnconfigure(3, weight=1)

        tk.Label(
            controls,
            text="Source",
            bg=SURFACE,
            fg=MUTED,
            font=("SF Pro Text", 11, "bold"),
        ).grid(row=0, column=0, sticky="w", padx=(14, 8), pady=10)

        self.source_var = tk.StringVar(value="Microphone")
        self.source_menu = ttk.Combobox(
            controls,
            textvariable=self.source_var,
            state="readonly",
            values=self.available_sources(),
            width=14,
        )
        self.source_menu.grid(row=0, column=1, padx=(0, 14), pady=10, ipady=4, sticky="w")
        self.source_menu.bind("<<ComboboxSelected>>", self.on_source_changed)

        tk.Label(
            controls,
            text="Input",
            bg=SURFACE,
            fg=MUTED,
            font=("SF Pro Text", 11, "bold"),
        ).grid(row=0, column=2, sticky="w", padx=(0, 8), pady=10)

        self.device_var = tk.StringVar()
        self.device_menu = ttk.Combobox(
            controls,
            textvariable=self.device_var,
            state="readonly",
            width=46,
        )
        self.device_menu.grid(row=0, column=3, padx=(0, 10), pady=10, ipady=4, sticky="ew")

        self.refresh_source_button = FlatButton(
            controls,
            text="Refresh",
            command=self.refresh_current_source,
            bg=SURFACE_ALT,
            fg=TEXT,
            active_bg=LINE,
            font=("SF Pro Text", 12),
            padx=10,
        )
        self.refresh_source_button.grid(row=0, column=4, padx=(0, 14), pady=10, sticky="ew")

        body = tk.Frame(self.root, bg=BG)
        body.grid(row=1, column=0, sticky="nsew", padx=18, pady=(0, 14))
        body.grid_columnconfigure(0, weight=1)
        body.grid_rowconfigure(1, weight=1)

        header = tk.Frame(body, bg=SURFACE_ALT, highlightbackground=LINE, highlightthickness=1)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(0, weight=1, uniform="columns")
        header.grid_columnconfigure(1, weight=1, uniform="columns")

        self.source_badge_label, self.source_header_label = self._header_label(header, 0, "", "", EN)
        self.target_badge_label, self.target_header_label = self._header_label(header, 1, "", "", RU)

        self.canvas = tk.Canvas(body, bg=BG, highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(body, orient="vertical", command=self.canvas.yview)
        self.rows_frame = tk.Frame(self.canvas, bg=BG)
        self.canvas_window = self.canvas.create_window((0, 0), window=self.rows_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        self.scrollbar.grid(row=1, column=1, sticky="ns", pady=(8, 0))

        self.rows_frame.bind("<Configure>", self._on_rows_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        for widget in (self.canvas, self.rows_frame):
            widget.bind("<Enter>", self._enable_transcript_scroll)
            widget.bind("<Leave>", self._disable_transcript_scroll)
        self.canvas.bind("<MouseWheel>", self._on_mousewheel)
        self.rows_frame.bind("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind("<Button-4>", self._on_mousewheel)
        self.canvas.bind("<Button-5>", self._on_mousewheel)
        self.rows_frame.bind("<Button-4>", self._on_mousewheel)
        self.rows_frame.bind("<Button-5>", self._on_mousewheel)
        self.root.bind_all("<MouseWheel>", self._on_global_mousewheel)
        self.root.bind_all("<Button-4>", self._on_global_mousewheel)
        self.root.bind_all("<Button-5>", self._on_global_mousewheel)

        footer = tk.Frame(self.root, bg=BG)
        footer.grid(row=2, column=0, sticky="ew", padx=18, pady=(0, 16))
        footer.grid_columnconfigure(1, weight=1)

        self.level_name_label = tk.Label(
            footer,
            text="Mic",
            bg=BG,
            fg=MUTED,
            font=("SF Pro Text", 11, "bold"),
        )
        self.level_name_label.grid(row=0, column=0, sticky="w", padx=(0, 8))

        self.level = ttk.Progressbar(footer, orient="horizontal", mode="determinate", maximum=100)
        self.level.grid(row=0, column=1, sticky="ew")

        self.answer_toggle = tk.Checkbutton(
            footer,
            text="Answer",
            variable=self.answer_var,
            command=self.toggle_answer_mode,
            bg=BG,
            fg=TEXT,
            selectcolor=SURFACE,
            activebackground=BG,
            activeforeground=TEXT,
            font=("SF Pro Text", 12),
        )
        self.answer_toggle.grid(row=0, column=2, sticky="e", padx=(12, 0))

        self.rag_toggle = tk.Checkbutton(
            footer,
            text="RAG",
            variable=self.rag_var,
            command=self.toggle_rag_mode,
            bg=BG,
            fg=TEXT,
            selectcolor=SURFACE,
            activebackground=BG,
            activeforeground=TEXT,
            font=("SF Pro Text", 12),
        )
        self.rag_toggle.grid(row=0, column=3, sticky="e", padx=(12, 0))

        self.timer_label = tk.Label(
            footer,
            text="00:00",
            bg=BG,
            fg=MUTED,
            font=("SF Mono", 11),
            padx=12,
        )
        self.timer_label.grid(row=0, column=4, sticky="e")

        self.empty_label = tk.Label(
            self.rows_frame,
            text="Нажми Start и говори по-английски. Здесь появятся пары EN/RU.",
            bg=BG,
            fg=MUTED,
            font=("SF Pro Text", 16),
            pady=80,
        )
        self.empty_label.pack(fill="x")
        self.bind_transcript_scroll(self.empty_label)

        self.apply_topmost()
        self.update_language_labels()
        self.update_config_label()

    def _header_label(self, parent, column, title, badge_text, color):
        box = tk.Frame(parent, bg=SURFACE_ALT)
        box.grid(row=0, column=column, sticky="ew", padx=12, pady=10)

        badge = tk.Label(
            box,
            text=badge_text,
            bg=color,
            fg="#101010",
            font=("SF Pro Text", 11, "bold"),
            padx=8,
            pady=2,
        )
        badge.pack(side="left")

        title_label = tk.Label(
            box,
            text=title,
            bg=SURFACE_ALT,
            fg=TEXT,
            font=("SF Pro Text", 13, "bold"),
            padx=8,
        )
        title_label.pack(side="left")
        return badge, title_label

    def refresh_devices(self):
        self.devices = list_input_devices()
        values = ["System default microphone"]
        self.device_values = {values[0]: None}
        for device in self.devices:
            default = " default" if device["is_default"] else ""
            value = f"[{device['index']}] {device['name']}{default}"
            values.append(value)
            self.device_values[value] = device["index"]
        self.device_menu.configure(values=values)
        self.device_var.set(values[0])
        self.level_name_label.configure(text="Mic")

    def available_sources(self):
        sources = ["Microphone"]
        if IS_MACOS:
            sources.extend(["Window audio", "App audio"])
        if IS_WINDOWS:
            sources.append("System audio")
        return sources

    def refresh_windows(self):
        self.set_status("Loading windows", WARN)
        try:
            self.windows = list_audio_windows()
        except Exception as exc:
            self.windows = []
            self.window_values = {}
            self.device_menu.configure(values=["No windows available"])
            self.device_var.set("No windows available")
            self.set_status("Window list error", ERROR)
            messagebox.showerror("Window audio", str(exc))
            return

        values = []
        self.window_values = {}
        hidden_apps = {"Dock", "Обои", "Window Server"}
        hidden_app_fragments = ("Open and Save Panel Service", "Заполнить автоматически")
        visible_windows = [
            window for window in self.windows
            if window.get("app")
            and window.get("app") not in hidden_apps
            and not any(fragment in window.get("app") for fragment in hidden_app_fragments)
        ]
        visible_windows.sort(
            key=lambda window: (
                str(window.get("app") or "").lower(),
                1 if (window.get("title") or "") == "(Untitled)" else 0,
                str(window.get("title") or "").lower(),
            )
        )

        for window in visible_windows:
            title = window.get("title") or "(Untitled)"
            app = window.get("app") or "Unknown app"
            value = f"{app} - {title} [{window.get('id')}]"
            values.append(value)
            self.window_values[value] = window.get("id")

        if not values:
            values = ["No capturable windows"]
        self.device_menu.configure(values=values)
        self.device_var.set(values[0])
        self.level_name_label.configure(text="Window")
        self.set_status("Ready", TEXT)

    def refresh_apps(self):
        self.set_status("Loading apps", WARN)
        try:
            self.apps = list_audio_apps()
        except Exception as exc:
            self.apps = []
            self.app_values = {}
            self.device_menu.configure(values=["No apps available"])
            self.device_var.set("No apps available")
            self.set_status("App list error", ERROR)
            messagebox.showerror("App audio", str(exc))
            return

        hidden_apps = {"Dock", "Обои", "Window Server"}
        visible_apps = [
            app for app in self.apps
            if app.get("app") and app.get("app") not in hidden_apps
        ]
        visible_apps.sort(key=lambda app: str(app.get("app") or "").lower())

        values = []
        self.app_values = {}
        for app in visible_apps:
            name = app.get("app") or "Unknown app"
            bundle = app.get("bundleIdentifier") or ""
            value = f"{name} [{app.get('pid')}]"
            if bundle:
                value = f"{name} - {bundle} [{app.get('pid')}]"
            values.append(value)
            self.app_values[value] = app.get("pid")

        if not values:
            values = ["No capturable apps"]
        self.device_menu.configure(values=values)
        self.device_var.set(values[0])
        self.level_name_label.configure(text="App")
        self.set_status("Ready", TEXT)

    def refresh_system_audio(self):
        self.set_status("Loading system audio", WARN)
        try:
            self.system_audio_devices = list_system_audio_devices()
        except Exception as exc:
            self.system_audio_devices = []
            self.system_audio_values = {}
            self.device_menu.configure(values=["No system audio available"])
            self.device_var.set("No system audio available")
            self.set_status("System audio error", ERROR)
            messagebox.showerror("System audio", str(exc))
            return

        values = ["Default system output"]
        self.system_audio_values = {values[0]: None}
        for device in self.system_audio_devices:
            default = " default" if device["is_default"] else ""
            value = f"{device['name']}{default}"
            values.append(value)
            self.system_audio_values[value] = device["id"]
        self.device_menu.configure(values=values)
        self.device_var.set(values[0])
        self.level_name_label.configure(text="System")
        self.set_status("Ready", TEXT)

    def on_source_changed(self, _event=None):
        self.refresh_current_source()

    def refresh_current_source(self):
        if self.source_var.get() == "Window audio":
            self.refresh_windows()
        elif self.source_var.get() == "App audio":
            self.refresh_apps()
        elif self.source_var.get() == "System audio":
            self.refresh_system_audio()
        else:
            self.refresh_devices()
            self.set_status("Ready", TEXT)

    def apply_topmost(self):
        self.root.attributes("-topmost", bool(self.pin_var.get()))

    def source_language(self):
        return language_info("en")

    def target_language(self):
        return language_info(self.settings["target_language_code"])

    def update_language_labels(self):
        source = self.source_language()
        target = self.target_language()
        self.direction_label.configure(text=f"Live {source['short']} -> {target['short']}")
        self.source_badge_label.configure(text=source["short"])
        self.source_header_label.configure(text=source["speech"])
        self.target_badge_label.configure(text=target["short"])
        self.target_header_label.configure(text=target["translation"])
        self.empty_label.configure(
            text=(
                f"Нажми Start и говори по-{source['name']}. "
                f"Здесь появятся пары {source['short']}/{target['short']}."
            )
        )

    def update_config_label(self):
        model = self.settings["model"] or DEFAULT_SETTINGS["model"]
        target = self.settings["target_language_code"] or DEFAULT_SETTINGS["target_language_code"]
        key_state = "API saved" if self.settings["api_key"] else "API missing"
        answer_state = (
            f"answer: {self.settings['answer_model']}"
            if self.settings["answer_enabled"]
            else "answer: off"
        )
        rag_state = (
            f"rag: {self.settings['embedding_model']} >= {float(self.settings['rag_min_similarity']):.2f}"
            if self.settings["rag_enabled"]
            else "rag: off"
        )
        mode_state = f"mode: {self.settings['transcript_mode']}"
        self.config_label.configure(
            text=f"{model} | target: {target} | {mode_state} | {answer_state} | {rag_state} | {key_state}"
        )

    def toggle_answer_mode(self):
        self.settings["answer_enabled"] = bool(self.answer_var.get())
        try:
            save_settings(self.settings)
        except OSError as exc:
            messagebox.showerror("Settings", f"Не удалось сохранить Answer mode: {exc}")
            self.answer_var.set(not self.answer_var.get())
            self.settings["answer_enabled"] = bool(self.answer_var.get())
            return
        self.update_config_label()
        self.set_status("Answer on" if self.settings["answer_enabled"] else "Answer off", RU)

    def toggle_rag_mode(self):
        self.settings["rag_enabled"] = bool(self.rag_var.get())
        try:
            save_settings(self.settings)
        except OSError as exc:
            messagebox.showerror("Settings", f"Не удалось сохранить RAG mode: {exc}")
            self.rag_var.set(not self.rag_var.get())
            self.settings["rag_enabled"] = bool(self.rag_var.get())
            return
        self.update_config_label()
        self.set_status("RAG on" if self.settings["rag_enabled"] else "RAG off", RU)

    def open_knowledge(self):
        if self.knowledge_window and self.knowledge_window.winfo_exists():
            self.knowledge_window.lift()
            return

        window = tk.Toplevel(self.root)
        self.knowledge_window = window
        window.title("Gem Translate Knowledge")
        window.geometry("820x560")
        window.minsize(740, 500)
        window.configure(bg=BG)
        window.transient(self.root)
        window.grid_columnconfigure(0, weight=1)
        window.grid_rowconfigure(2, weight=1)

        header = tk.Frame(window, bg=BG)
        header.grid(row=0, column=0, sticky="ew", padx=18, pady=(18, 10))
        header.grid_columnconfigure(0, weight=1)

        tk.Label(
            header,
            text="Knowledge Base",
            bg=BG,
            fg=TEXT,
            font=("SF Pro Display", 20, "bold"),
        ).grid(row=0, column=0, sticky="w")

        stats_label = tk.Label(
            header,
            text="",
            bg=BG,
            fg=MUTED,
            font=("SF Pro Text", 11),
            anchor="w",
        )
        stats_label.grid(row=1, column=0, sticky="ew", pady=(4, 0))

        actions = tk.Frame(header, bg=BG)
        actions.grid(row=0, column=1, rowspan=2, sticky="e")

        list_frame = tk.Frame(window, bg=SURFACE, highlightbackground=LINE, highlightthickness=1)
        list_frame.grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 12))
        list_frame.grid_columnconfigure(0, weight=1)

        sources_list = tk.Listbox(
            list_frame,
            bg=SURFACE,
            fg=TEXT,
            selectbackground="#35506a",
            selectforeground=TEXT,
            highlightthickness=0,
            relief="flat",
            height=7,
            font=("SF Pro Text", 12),
        )
        sources_list.grid(row=0, column=0, sticky="ew", padx=10, pady=10)

        preview = tk.Text(
            window,
            bg=SURFACE,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            wrap="word",
            font=("SF Pro Text", 12),
            padx=12,
            pady=12,
        )
        preview.grid(row=2, column=0, sticky="nsew", padx=18, pady=(0, 18))

        def selected_source():
            selection = sources_list.curselection()
            if not selection:
                return None
            data = load_knowledge()
            index = selection[0]
            if index >= len(data["sources"]):
                return None
            return data["sources"][index]

        def refresh_view():
            data = load_knowledge()
            stats = knowledge_stats()
            stats_label.configure(
                text=(
                    f"{stats['sources']} files | {stats['chunks']} chunks | "
                    f"{stats['embedded_chunks']} embedded | "
                    f"{stats['chars']} chars | {stats['path']}"
                )
            )
            sources_list.delete(0, tk.END)
            for source in data["sources"]:
                sources_list.insert(
                    tk.END,
                    f"{source.get('name')} | {source.get('chunks', 0)} chunks | {source.get('added_at')}",
                )
            preview.delete("1.0", tk.END)
            if data["sources"]:
                sources_list.selection_set(tk.END)
                show_source_preview()
            else:
                preview.insert(
                    "1.0",
                    "Добавь .txt/.md файл с опытом, проектами, резюме, портфолио или личной историей.\n\n"
                    "Новые файлы добавляются к существующей базе, не заменяя ее.",
                )

        def show_source_preview(_event=None):
            source = selected_source()
            preview.delete("1.0", tk.END)
            if not source:
                return
            data = load_knowledge()
            chunks = [
                chunk for chunk in data["chunks"]
                if chunk.get("source_id") == source.get("id")
            ]
            preview.insert(
                "1.0",
                (
                    f"File: {source.get('name')}\n"
                    f"Path: {source.get('path')}\n"
                    f"Added: {source.get('added_at')}\n"
                    f"Chunks: {source.get('chunks', 0)}\n\n"
                    f"Embedding model: {source.get('embedding_model', 'not indexed')}\n\n"
                ),
            )
            for chunk in chunks[:3]:
                preview.insert(tk.END, f"--- Chunk {chunk.get('index', 0) + 1} ---\n")
                preview.insert(tk.END, chunk.get("text", "")[:1400])
                preview.insert(tk.END, "\n\n")

        def add_file():
            if not self.settings["api_key"]:
                messagebox.showerror("Knowledge", "Сначала сохрани Google API key в Settings.")
                return
            path = filedialog.askopenfilename(
                title="Add knowledge text file",
                filetypes=[
                    ("Text files", "*.txt *.md *.markdown"),
                    ("All files", "*.*"),
                ],
            )
            if not path:
                return
            try:
                self.set_status("Embedding file", WARN)
                source = add_text_file(
                    path,
                    api_key=self.settings["api_key"],
                    embedding_model=self.settings["embedding_model"],
                )
            except Exception as exc:
                messagebox.showerror("Knowledge", f"Не удалось добавить файл: {exc}")
                return
            self.set_status("Knowledge added", RU)
            refresh_view()
            messagebox.showinfo(
                "Knowledge",
                f"Добавлено: {source['name']}\nChunks: {source['chunks']}",
            )

        def clear_base():
            if not messagebox.askyesno("Knowledge", "Очистить всю knowledge base?"):
                return
            clear_knowledge()
            self.set_status("Knowledge cleared", WARN)
            refresh_view()

        def rebuild_base():
            if not self.settings["api_key"]:
                messagebox.showerror("Knowledge", "Сначала сохрани Google API key в Settings.")
                return
            if not messagebox.askyesno(
                "Knowledge",
                f"Пересчитать embeddings для всей базы через {self.settings['embedding_model']}?",
            ):
                return
            try:
                self.set_status("Rebuilding embeddings", WARN)
                rebuild_embeddings(
                    api_key=self.settings["api_key"],
                    embedding_model=self.settings["embedding_model"],
                )
            except Exception as exc:
                messagebox.showerror("Knowledge", f"Не удалось пересчитать embeddings: {exc}")
                return
            self.set_status("Embeddings rebuilt", RU)
            refresh_view()

        FlatButton(
            actions,
            text="Add Text File",
            command=add_file,
            bg=RU,
            fg="#101010",
            active_bg="#95e9a5",
            padx=14,
        ).pack(side="left", padx=(0, 8))

        FlatButton(
            actions,
            text="Rebuild Embeddings",
            command=rebuild_base,
            bg=SURFACE_ALT,
            fg=TEXT,
            active_bg=LINE,
            padx=14,
        ).pack(side="left", padx=(0, 8))

        FlatButton(
            actions,
            text="Clear Base",
            command=clear_base,
            bg=ERROR,
            fg="#101010",
            active_bg="#ff8a8a",
            padx=14,
        ).pack(side="left")

        sources_list.bind("<<ListboxSelect>>", show_source_preview)
        refresh_view()

    def open_prompt(self):
        if self.prompt_window and self.prompt_window.winfo_exists():
            self.prompt_window.lift()
            return

        window = tk.Toplevel(self.root)
        self.prompt_window = window
        window.title("Gem Translate Answer Prompt")
        window.geometry("760x520")
        window.minsize(660, 460)
        window.configure(bg=BG)
        window.transient(self.root)
        window.grid_columnconfigure(0, weight=1)
        window.grid_rowconfigure(1, weight=1)

        header = tk.Frame(window, bg=BG)
        header.grid(row=0, column=0, sticky="ew", padx=18, pady=(18, 10))
        header.grid_columnconfigure(0, weight=1)

        tk.Label(
            header,
            text="Answer Prompt",
            bg=BG,
            fg=TEXT,
            font=("SF Pro Display", 20, "bold"),
        ).grid(row=0, column=0, sticky="w")

        tk.Label(
            header,
            text="Works for simple answers and RAG answers. RAG context is added separately when enabled.",
            bg=BG,
            fg=MUTED,
            font=("SF Pro Text", 11),
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))

        prompt_text = tk.Text(
            window,
            bg=SURFACE,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            wrap="word",
            font=("SF Pro Text", 13),
            padx=12,
            pady=12,
        )
        prompt_text.grid(row=1, column=0, sticky="nsew", padx=18, pady=(0, 14))
        prompt_text.insert("1.0", self.settings.get("answer_prompt", DEFAULT_SETTINGS["answer_prompt"]))

        buttons = tk.Frame(window, bg=BG)
        buttons.grid(row=2, column=0, sticky="e", padx=18, pady=(0, 18))

        def reset_prompt():
            prompt_text.delete("1.0", tk.END)
            prompt_text.insert("1.0", DEFAULT_SETTINGS["answer_prompt"])

        def save_prompt():
            self.settings["answer_prompt"] = prompt_text.get("1.0", tk.END).strip()
            if not self.settings["answer_prompt"]:
                self.settings["answer_prompt"] = DEFAULT_SETTINGS["answer_prompt"]
            try:
                save_settings(self.settings)
            except OSError as exc:
                messagebox.showerror("Prompt", f"Не удалось сохранить prompt: {exc}")
                return
            self.set_status("Prompt saved", RU)
            window.destroy()

        FlatButton(
            buttons,
            text="Reset",
            command=reset_prompt,
            bg=SURFACE_ALT,
            fg=TEXT,
            active_bg=LINE,
            padx=16,
        ).pack(side="right", padx=(8, 0))

        FlatButton(
            buttons,
            text="Save",
            command=save_prompt,
            bg=RU,
            fg="#101010",
            active_bg="#95e9a5",
            padx=18,
        ).pack(side="right")

    def open_settings(self):
        if self.settings_window and self.settings_window.winfo_exists():
            self.settings_window.lift()
            return

        window = tk.Toplevel(self.root)
        self.settings_window = window
        window.title("Gem Translate Settings")
        window.geometry("760x760")
        window.minsize(700, 720)
        window.configure(bg=BG)
        window.transient(self.root)
        window.grid_columnconfigure(0, weight=1)

        frame = tk.Frame(window, bg=BG)
        frame.grid(row=0, column=0, sticky="nsew", padx=18, pady=18)
        frame.grid_columnconfigure(1, weight=1)

        api_var = tk.StringVar(value=self.settings["api_key"])
        model_var = tk.StringVar(value=self.settings["model"])
        target_var = tk.StringVar(value=self.settings["target_language_code"])
        echo_var = tk.BooleanVar(value=bool(self.settings["echo_target_language"]))
        transcript_mode_var = tk.StringVar(value=self.settings["transcript_mode"])
        answer_enabled_var = tk.BooleanVar(value=bool(self.settings["answer_enabled"]))
        answer_model_var = tk.StringVar(value=self.settings["answer_model"])
        answer_language_var = tk.StringVar(value=self.settings["answer_language"])
        rag_enabled_var = tk.BooleanVar(value=bool(self.settings["rag_enabled"]))
        embedding_model_var = tk.StringVar(value=self.settings["embedding_model"])
        rag_min_similarity_var = tk.StringVar(value=str(self.settings["rag_min_similarity"]))
        rag_top_k_var = tk.StringVar(value=str(self.settings["rag_top_k"]))

        self._settings_label(frame, 0, "Google API key")
        api_entry = tk.Entry(
            frame,
            textvariable=api_var,
            show="•",
            bg=SURFACE,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            font=("SF Mono", 12),
        )
        api_entry.grid(row=0, column=1, sticky="ew", pady=8, ipady=8)

        show_var = tk.BooleanVar(value=False)

        def toggle_key():
            api_entry.configure(show="" if show_var.get() else "•")

        tk.Checkbutton(
            frame,
            text="Show",
            variable=show_var,
            command=toggle_key,
            bg=BG,
            fg=TEXT,
            selectcolor=SURFACE,
            activebackground=BG,
            activeforeground=TEXT,
            font=("SF Pro Text", 11),
        ).grid(row=0, column=2, sticky="w", padx=(10, 0))

        self._settings_label(frame, 1, "Translation model")
        model_box = ttk.Combobox(
            frame,
            textvariable=model_var,
            values=[
                "gemini-3.5-live-translate-preview",
            ],
        )
        model_box.grid(row=1, column=1, columnspan=2, sticky="ew", pady=8, ipady=4)

        self._settings_label(frame, 2, "Target language")
        target_box = ttk.Combobox(
            frame,
            textvariable=target_var,
            values=["ru", "en", "hy", "es", "de", "fr", "it", "pt", "tr"],
            width=10,
        )
        target_box.grid(row=2, column=1, sticky="w", pady=8, ipady=4)

        tk.Checkbutton(
            frame,
            text="Echo target language audio",
            variable=echo_var,
            bg=BG,
            fg=TEXT,
            selectcolor=SURFACE,
            activebackground=BG,
            activeforeground=TEXT,
            font=("SF Pro Text", 12),
        ).grid(row=3, column=1, columnspan=2, sticky="w", pady=(8, 16))

        self._settings_label(frame, 4, "Transcript mode")
        transcript_mode_box = ttk.Combobox(
            frame,
            textvariable=transcript_mode_var,
            values=["interview", "fast"],
            state="readonly",
            width=14,
        )
        transcript_mode_box.grid(row=4, column=1, sticky="w", pady=8, ipady=4)

        tk.Label(
            frame,
            text="interview = grouped turns + answers | fast = immediate stream",
            bg=BG,
            fg=MUTED,
            font=("SF Pro Text", 10),
        ).grid(row=4, column=1, sticky="w", padx=(150, 0), pady=8)

        separator = tk.Frame(frame, bg=LINE, height=1)
        separator.grid(row=5, column=0, columnspan=3, sticky="ew", pady=(4, 14))

        tk.Checkbutton(
            frame,
            text="Enable answer model",
            variable=answer_enabled_var,
            bg=BG,
            fg=TEXT,
            selectcolor=SURFACE,
            activebackground=BG,
            activeforeground=TEXT,
            font=("SF Pro Text", 12, "bold"),
        ).grid(row=6, column=1, columnspan=2, sticky="w", pady=8)

        self._settings_label(frame, 7, "Answer model")
        answer_model_box = ttk.Combobox(
            frame,
            textvariable=answer_model_var,
            values=[
                "gemini-2.5-flash",
                "gemini-3.5-flash",
                "gemini-2.5-pro",
            ],
        )
        answer_model_box.grid(row=7, column=1, columnspan=2, sticky="ew", pady=8, ipady=4)

        self._settings_label(frame, 8, "Answer language")
        answer_language_box = ttk.Combobox(
            frame,
            textvariable=answer_language_var,
            values=["ru", "en", "hy", "es", "de", "fr", "it", "pt", "tr"],
            width=10,
        )
        answer_language_box.grid(row=8, column=1, sticky="w", pady=8, ipady=4)

        separator2 = tk.Frame(frame, bg=LINE, height=1)
        separator2.grid(row=9, column=0, columnspan=3, sticky="ew", pady=(4, 14))

        tk.Checkbutton(
            frame,
            text="Enable RAG knowledge",
            variable=rag_enabled_var,
            bg=BG,
            fg=TEXT,
            selectcolor=SURFACE,
            activebackground=BG,
            activeforeground=TEXT,
            font=("SF Pro Text", 12, "bold"),
        ).grid(row=10, column=1, columnspan=2, sticky="w", pady=8)

        self._settings_label(frame, 11, "Embedding model")
        embedding_model_box = ttk.Combobox(
            frame,
            textvariable=embedding_model_var,
            values=[
                "gemini-embedding-2",
                "gemini-embedding-001",
            ],
        )
        embedding_model_box.grid(row=11, column=1, columnspan=2, sticky="ew", pady=8, ipady=4)

        self._settings_label(frame, 12, "Min similarity")
        min_similarity_entry = tk.Entry(
            frame,
            textvariable=rag_min_similarity_var,
            bg=SURFACE,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            font=("SF Mono", 12),
            width=10,
        )
        min_similarity_entry.grid(row=12, column=1, sticky="w", pady=8, ipady=8)

        tk.Label(
            frame,
            text="0.30 loose | 0.42 balanced | 0.55 strict",
            bg=BG,
            fg=MUTED,
            font=("SF Pro Text", 10),
        ).grid(row=12, column=1, sticky="w", padx=(110, 0), pady=8)

        self._settings_label(frame, 13, "Top chunks")
        top_k_entry = tk.Entry(
            frame,
            textvariable=rag_top_k_var,
            bg=SURFACE,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            font=("SF Mono", 12),
            width=10,
        )
        top_k_entry.grid(row=13, column=1, sticky="w", pady=8, ipady=8)

        path_label = tk.Label(
            frame,
            text=f"Saved in {SETTINGS_PATH}",
            bg=BG,
            fg=MUTED,
            font=("SF Pro Text", 10),
            anchor="w",
        )
        path_label.grid(row=14, column=0, columnspan=3, sticky="ew", pady=(4, 16))

        buttons = tk.Frame(frame, bg=BG)
        buttons.grid(row=15, column=0, columnspan=3, sticky="e")

        def save_and_close():
            try:
                rag_min_similarity = float(rag_min_similarity_var.get().strip())
                rag_top_k = int(rag_top_k_var.get().strip())
            except ValueError:
                messagebox.showerror("Settings", "Min similarity должен быть числом, Top chunks целым числом.")
                return
            rag_min_similarity = max(0.0, min(1.0, rag_min_similarity))
            rag_top_k = max(1, min(12, rag_top_k))
            self.settings = {
                "api_key": api_var.get().strip(),
                "model": model_var.get().strip() or DEFAULT_SETTINGS["model"],
                "target_language_code": target_var.get().strip() or DEFAULT_SETTINGS["target_language_code"],
                "echo_target_language": bool(echo_var.get()),
                "transcript_mode": transcript_mode_var.get().strip() or DEFAULT_SETTINGS["transcript_mode"],
                "answer_enabled": bool(answer_enabled_var.get()),
                "answer_model": answer_model_var.get().strip() or DEFAULT_SETTINGS["answer_model"],
                "answer_language": answer_language_var.get().strip() or DEFAULT_SETTINGS["answer_language"],
                "answer_prompt": self.settings.get("answer_prompt", DEFAULT_SETTINGS["answer_prompt"]),
                "rag_enabled": bool(rag_enabled_var.get()),
                "embedding_model": embedding_model_var.get().strip() or DEFAULT_SETTINGS["embedding_model"],
                "rag_min_similarity": rag_min_similarity,
                "rag_top_k": rag_top_k,
            }
            self.answer_var.set(bool(self.settings["answer_enabled"]))
            self.rag_var.set(bool(self.settings["rag_enabled"]))
            if self.settings["transcript_mode"] == "fast":
                for row in self.rows:
                    if row.finalize_after_id:
                        self.root.after_cancel(row.finalize_after_id)
                        row.finalize_after_id = None
            try:
                save_settings(self.settings)
            except OSError as exc:
                messagebox.showerror("Settings", f"Не удалось сохранить настройки: {exc}")
                return
            self.update_language_labels()
            self.update_config_label()
            self.set_status("Settings saved", RU)
            window.destroy()

        FlatButton(
            buttons,
            text="Cancel",
            command=window.destroy,
            bg=SURFACE_ALT,
            fg=TEXT,
            active_bg=LINE,
            font=("SF Pro Text", 13),
            padx=16,
        ).pack(side="right", padx=(8, 0))

        FlatButton(
            buttons,
            text="Save",
            command=save_and_close,
            bg=RU,
            fg="#101010",
            active_bg="#95e9a5",
            font=("SF Pro Text", 13, "bold"),
            padx=18,
        ).pack(side="right")

        api_entry.focus_set()

    def _settings_label(self, parent, row, text):
        tk.Label(
            parent,
            text=text,
            bg=BG,
            fg=MUTED,
            font=("SF Pro Text", 12, "bold"),
            anchor="w",
        ).grid(row=row, column=0, sticky="w", padx=(0, 14), pady=8)

    def start(self):
        if self.worker and self.worker.is_alive():
            return
        if not self.settings["api_key"]:
            messagebox.showerror(
                "GOOGLE_API_KEY",
                "Открой Settings и сохрани Google API key перед запуском перевода.",
            )
            self.set_status("No API key", ERROR)
            return

        self.stop_flag.clear()
        self.started_at = time.time()
        self.set_running(True)
        self.set_status("Connecting", WARN)
        source_choice = self.source_var.get()
        if source_choice == "Window audio":
            source_type = "window"
        elif source_choice == "App audio":
            source_type = "app"
        elif source_choice == "System audio":
            source_type = "system_audio"
        else:
            source_type = "microphone"
        device_index = None
        window_id = None
        app_pid = None
        system_audio_id = None
        if source_type == "window":
            window_id = self.window_values.get(self.device_var.get())
            if window_id is None:
                self.set_running(False)
                self.set_status("No window", ERROR)
                messagebox.showerror("Window audio", "Выбери окно для захвата аудио.")
                return
        elif source_type == "app":
            app_pid = self.app_values.get(self.device_var.get())
            if app_pid is None:
                self.set_running(False)
                self.set_status("No app", ERROR)
                messagebox.showerror("App audio", "Выбери приложение для захвата аудио.")
                return
        elif source_type == "system_audio":
            system_audio_id = self.system_audio_values.get(self.device_var.get())
            if self.device_var.get() not in self.system_audio_values:
                self.set_running(False)
                self.set_status("No system audio", ERROR)
                messagebox.showerror("System audio", "Выбери system audio device.")
                return
        else:
            device_index = self.device_values.get(self.device_var.get())
        settings = self.settings.copy()
        self.worker = threading.Thread(
            target=self._worker_main,
            args=(source_type, device_index, window_id, app_pid, system_audio_id, settings),
            daemon=True,
        )
        self.worker.start()

    def _worker_main(self, source_type, device_index, window_id, app_pid, system_audio_id, settings):
        def push(kind, value=None):
            self.events.put((kind, value))

        async def run():
            await capture_and_translate(
                device_index=device_index,
                source_type=source_type,
                window_id=window_id,
                app_pid=app_pid,
                system_audio_id=system_audio_id,
                api_key=settings["api_key"],
                model=settings["model"],
                target_language_code=settings["target_language_code"],
                echo_target_language=settings["echo_target_language"],
                on_input=lambda text: push("input", text),
                on_output=lambda text: push("output", text),
                on_level=lambda value: push("level", value),
                on_status=lambda value: push("status", value),
                should_stop=self.stop_flag.is_set,
            )

        try:
            asyncio.run(run())
        except Exception as exc:
            push("error", str(exc))
        finally:
            push("done")

    def stop(self):
        if self.worker and self.worker.is_alive():
            self.stop_flag.set()
            self.set_status("Stopping", WARN)
            self.stop_button.configure(state="disabled")

    def clear(self):
        for row in self.rows:
            if row.answer_after_id:
                self.root.after_cancel(row.answer_after_id)
            if row.finalize_after_id:
                self.root.after_cancel(row.finalize_after_id)
            row.frame.destroy()
        self.rows.clear()
        self.current_row = None
        self.empty_label.pack(fill="x")
        self.canvas.yview_moveto(0)

    def close(self):
        self.stop_flag.set()
        self.root.after(120, self.root.destroy)

    def poll_events(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "input":
                    self.add_english(value)
                elif kind == "output":
                    self.add_russian(value)
                elif kind == "answer":
                    row, text = value
                    self.apply_answer(row, text)
                elif kind == "answer_error":
                    row, text = value
                    self.apply_answer(row, f"Answer error: {text}")
                elif kind == "level":
                    self.set_level(value)
                elif kind == "status":
                    self.handle_status(value)
                elif kind == "error":
                    self.set_status("Error", ERROR)
                    messagebox.showerror("Gem Translate", value)
                elif kind == "done":
                    self.set_running(False)
                    self.set_status("Ready", TEXT)
        except queue.Empty:
            pass
        self.root.after(80, self.poll_events)

    def handle_status(self, value):
        if value == "connected":
            self.set_status("Listening", RU)
        elif value == "opening_window":
            self.set_status("Opening window", WARN)
        elif value == "opening_app":
            self.set_status("Opening app", WARN)
        elif value == "opening_system_audio":
            self.set_status("Opening system", WARN)
        elif value == "listening":
            self.set_status("Opening mic", WARN)
        elif value == "error":
            self.set_status("Error", ERROR)
        elif value == "stopped":
            self.set_status("Ready", TEXT)

    def set_status(self, text, color):
        self.status_label.configure(text=text, fg=color)

    def set_running(self, is_running):
        self.start_button.configure(state="disabled" if is_running else "normal")
        self.stop_button.configure(state="normal" if is_running else "disabled")
        self.device_menu.configure(state="disabled" if is_running else "readonly")
        self.source_menu.configure(state="disabled" if is_running else "readonly")
        self.refresh_source_button.configure(state="disabled" if is_running else "normal")
        if not is_running:
            self.started_at = None
            self.level.configure(value=0)

    def set_level(self, raw_level):
        self.last_level = raw_level
        normalized = min(100, int(raw_level / 35))
        self.level.configure(value=normalized)

    def add_english(self, text):
        if self.settings["transcript_mode"] == "fast":
            self.add_english_fast(text)
            return
        if self.current_row is None or self.current_row.finalized:
            self.current_row = self._new_row()
        row = self.current_row
        row.set_english(merge_text(row.english, text))
        row.set_finalized(False)
        self.schedule_turn_finalize(row)
        self.scroll_to_bottom()

    def add_russian(self, text):
        if self.settings["transcript_mode"] == "fast":
            self.add_russian_fast(text)
            return
        if self.current_row is None:
            if self.rows and not self.rows[-1].russian:
                self.current_row = self.rows[-1]
                self.current_row.set_finalized(False)
            else:
                self.current_row = self._new_row()
        if self.current_row.finalized and not self.current_row.russian:
            self.current_row.set_finalized(False)
        elif self.current_row.finalized:
            self.current_row = self._new_row()
        row = self.current_row
        row.set_russian(merge_text(row.russian, text))
        row.set_finalized(False)
        self.schedule_turn_finalize(row)
        self.scroll_to_bottom()

    def add_english_fast(self, text):
        if self.current_row is None or self.current_row.russian:
            self.current_row = self._new_row()
        row = self.current_row
        row.set_english(merge_text(row.english, text))
        row.set_finalized(False)
        self.scroll_to_bottom()

    def add_russian_fast(self, text):
        if self.current_row is None:
            self.current_row = self._new_row()
        row = self.current_row
        row.set_russian(merge_text(row.russian, text))
        row.set_finalized(True)
        self.current_row = None
        self.scroll_to_bottom()

    def schedule_turn_finalize(self, row):
        if row.finalize_after_id:
            self.root.after_cancel(row.finalize_after_id)
        row.finalize_after_id = self.root.after(
            TURN_FINALIZE_MS,
            lambda: self.finalize_turn(row),
        )

    def finalize_turn(self, row):
        row.finalize_after_id = None
        if row not in self.rows or not row.frame.winfo_exists():
            return
        if not row.english.strip() and not row.russian.strip():
            return
        row.set_finalized(True)
        if self.current_row is row:
            self.current_row = None
        self.schedule_answer(row)

    def schedule_answer(self, row):
        if not self.settings["answer_enabled"]:
            return
        if row.answer_after_id:
            self.root.after_cancel(row.answer_after_id)
        row.answer_after_id = self.root.after(250, lambda: self.request_answer(row))

    def request_answer(self, row):
        row.answer_after_id = None
        if row not in self.rows or not row.frame.winfo_exists():
            return
        if not self.settings["answer_enabled"]:
            return
        if not looks_like_question(row.english, row.russian):
            return

        question_key = f"{row.english.strip()}\n{row.russian.strip()}"
        if row.answer_requested_text == question_key:
            return
        row.answer_requested_text = question_key
        row.set_answer("Thinking...")
        self.scroll_to_bottom()

        settings = self.settings.copy()
        english_text = row.english
        russian_text = row.russian
        recent_context = self.recent_context(row)
        rag_context = ""
        if settings["rag_enabled"]:
            try:
                rag_context, _sources = retrieve_context(
                    f"{english_text}\n{russian_text}\n{recent_context}",
                    api_key=settings["api_key"],
                    embedding_model=settings["embedding_model"],
                    limit=settings["rag_top_k"],
                    min_similarity=settings["rag_min_similarity"],
                )
            except Exception as exc:
                self.events.put(("answer_error", (row, f"RAG retrieval error: {exc}")))
                return
            if _sources:
                best = _sources[0]
                source_name = best.get("source_name", "knowledge")
                rag_note = f"RAG used: {source_name} #{best.get('index', 0) + 1}, score {best.get('score', 0):.3f}"
            else:
                rag_note = f"RAG skipped: no chunk >= {settings['rag_min_similarity']:.2f}"
        else:
            rag_note = "RAG off"
        thread = threading.Thread(
            target=self._answer_worker,
            args=(row, english_text, russian_text, recent_context, rag_context, rag_note, settings),
            daemon=True,
        )
        thread.start()

    def _answer_worker(self, row, english_text, russian_text, recent_context, rag_context, rag_note, settings):
        try:
            answer = generate_answer(
                api_key=settings["api_key"],
                model=settings["answer_model"],
                english_text=english_text,
                russian_text=russian_text,
                recent_context=recent_context,
                rag_context=rag_context,
                custom_prompt=settings.get("answer_prompt", DEFAULT_SETTINGS["answer_prompt"]),
                answer_language=settings["answer_language"],
            )
            final_answer = answer or "No answer."
            if rag_note:
                final_answer = f"{rag_note}\n\n{final_answer}"
            self.events.put(("answer", (row, final_answer)))
        except Exception as exc:
            self.events.put(("answer_error", (row, str(exc))))

    def recent_context(self, current_row):
        context_rows = []
        source_short = self.source_language()["short"]
        target_short = self.target_language()["short"]
        for row in self.rows:
            if row is current_row:
                break
            if not row.finalized:
                continue
            english = row.english.strip()
            russian = row.russian.strip()
            if english or russian:
                context_rows.append(f"{source_short}: {english}\n{target_short}: {russian}")
        return "\n\n".join(context_rows[-5:])

    def apply_answer(self, row, text):
        if row not in self.rows or not row.frame.winfo_exists():
            return
        row.set_answer(text)
        self.scroll_to_bottom()

    def _new_row(self):
        if self.empty_label.winfo_ismapped():
            self.empty_label.pack_forget()
        timestamp = time.strftime("%H:%M")
        row = TranscriptRow(
            self.rows_frame,
            timestamp,
            self.source_language(),
            self.target_language(),
        )
        row.frame.pack(fill="x", expand=True)
        self.bind_transcript_scroll(row.frame)
        row.set_wraplength(self.canvas.winfo_width())
        self.rows.append(row)
        return row

    def scroll_to_bottom(self):
        self.root.after_idle(lambda: self.canvas.yview_moveto(1))

    def tick(self):
        if self.started_at:
            elapsed = int(time.time() - self.started_at)
            minutes, seconds = divmod(elapsed, 60)
            self.timer_label.configure(text=f"{minutes:02d}:{seconds:02d}")
        else:
            self.timer_label.configure(text="00:00")
        self.root.after(400, self.tick)

    def _on_rows_configure(self, _event):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        self.canvas.itemconfigure(self.canvas_window, width=event.width)
        for row in self.rows:
            row.set_wraplength(event.width)

    def bind_transcript_scroll(self, widget):
        widget.bind("<Enter>", self._enable_transcript_scroll)
        widget.bind("<Leave>", self._disable_transcript_scroll)
        widget.bind("<MouseWheel>", self._on_mousewheel)
        widget.bind("<Button-4>", self._on_mousewheel)
        widget.bind("<Button-5>", self._on_mousewheel)
        for child in widget.winfo_children():
            self.bind_transcript_scroll(child)

    def _enable_transcript_scroll(self, _event=None):
        self.transcript_scroll_active = True

    def _disable_transcript_scroll(self, _event=None):
        self.transcript_scroll_active = False

    def _on_global_mousewheel(self, event):
        if self.transcript_scroll_active:
            return self._on_mousewheel(event)
        return None

    def _on_mousewheel(self, event):
        if event.num == 4:
            units = -3
        elif event.num == 5:
            units = 3
        else:
            delta = getattr(event, "delta", 0)
            if delta == 0:
                return "break"
            units = -1 * int(delta / abs(delta)) * max(1, min(6, abs(delta) // 30))
        self.canvas.yview_scroll(units, "units")
        return "break"

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    load_local_env()
    GemTranslateApp().run()
