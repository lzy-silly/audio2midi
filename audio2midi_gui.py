# -*- coding: utf-8 -*-
"""
音频转 MIDI 工具（中文 GUI）
基于 Spotify 开源项目 basic-pitch + Python 标准库 tkinter

特性：
  - 完整图形界面：文件列表、输出目录、参数预设与精细调节
  - 推理在独立线程执行，UI 永不卡死，支持随时取消
  - 实时日志面板（分级配色）、进度条、状态提示
  - 一键环境检测与依赖安装，开箱即用
"""

from __future__ import annotations

import ctypes
import os
import queue
import subprocess
import sys
import threading
import time
import traceback
from importlib import metadata
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

# 在进入模型推理前压低 TensorFlow 的日志噪音
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
os.environ.setdefault("TF_ENABLE_ONEDNN_OPTS", "0")

APP_TITLE = "音频转 MIDI 工具"
APP_VERSION = "1.0.0"
SUPPORTED_EXT = {
    ".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac",
    ".aiff", ".aif", ".opus", ".mp4", ".webm",
}
AUDIO_FILE_TYPES = (
    ("音频文件", "*.wav *.mp3 *.flac *.ogg *.m4a *.aac *.aiff *.aif *.opus *.mp4 *.webm"),
    ("所有文件", "*.*"),
)

# 深色主题配色
BG = "#1e1e22"
PANEL = "#25252b"
DARK = "#161619"
TEXT = "#e8e8ea"
MUTED = "#969ba3"
ACCENT = "#4c9aff"
GREEN = "#6fd08c"
YELLOW = "#e5c07b"
RED = "#ff7b72"

FONT = ("Microsoft YaHei UI", 10)
FONT_BOLD = ("Microsoft YaHei UI", 10, "bold")

# 常用场景参数预设
PRESETS = {
    "通用": dict(onset=0.50, frame=0.30, min_len=127.7, min_freq=0.0,
                 max_freq=0.0, bpm=120, velocity=100, melodia=True, bends=False),
    "人声演唱": dict(onset=0.45, frame=0.25, min_len=110.0, min_freq=80.0,
                     max_freq=1200.0, bpm=120, velocity=100, melodia=True, bends=False),
    "吉他": dict(onset=0.55, frame=0.35, min_len=130.0, min_freq=60.0,
                 max_freq=2000.0, bpm=120, velocity=100, melodia=False, bends=False),
    "钢琴": dict(onset=0.50, frame=0.30, min_len=90.0, min_freq=30.0,
                 max_freq=5000.0, bpm=120, velocity=100, melodia=False, bends=False),
    "自定义": dict(onset=0.50, frame=0.30, min_len=127.7, min_freq=0.0,
                   max_freq=0.0, bpm=120, velocity=100, melodia=True, bends=False),
}


def setup_style() -> None:
    """统一配置 ttk 深色主题。"""
    style = ttk.Style()
    style.theme_use("clam")
    style.configure(".", font=FONT, background=BG, foreground=TEXT,
                    fieldbackground=PANEL, insertcolor=TEXT)
    style.configure("TFrame", background=BG)
    style.configure("TLabel", background=BG, foreground=TEXT)
    style.configure("TLabelframe", background=BG, foreground=ACCENT, bordercolor="#3a3a42")
    style.configure("TLabelframe.Label", background=BG, foreground=ACCENT, font=FONT_BOLD)
    style.configure("TButton", background="#33333a", foreground=TEXT, padding=5)
    style.map("TButton",
              background=[("active", "#41414a"), ("disabled", "#292930")],
              foreground=[("disabled", MUTED)])
    style.configure("Accent.TButton", background="#2c6fd6", foreground="#ffffff", font=FONT_BOLD)
    style.map("Accent.TButton",
              background=[("active", "#3b82f0"), ("disabled", "#292930")],
              foreground=[("disabled", MUTED)])
    style.configure("TEntry", fieldbackground=PANEL, foreground=TEXT, insertcolor=TEXT)
    style.configure("TSpinbox", fieldbackground=PANEL, foreground=TEXT, insertcolor=TEXT)
    style.configure("TCombobox", fieldbackground=PANEL, foreground=TEXT, insertcolor=TEXT)
    style.configure("TScale", background=BG, troughcolor="#3a3a42")
    style.configure("Horizontal.TScale", background=BG, troughcolor="#3a3a42")
    style.configure("TCheckbutton", background=BG, foreground=TEXT)
    style.map("TCheckbutton", background=[("active", BG)])
    style.configure("Treeview", background=PANEL, fieldbackground=PANEL,
                    foreground=TEXT, rowheight=24, borderwidth=0)
    style.configure("Treeview.Heading", background="#33333a", foreground=TEXT, padding=4)
    style.map("Treeview", background=[("selected", "#2c6fd6")],
              foreground=[("selected", "#ffffff")])


class App:
    """主窗口：所有 tkinter 操作只在主线程执行。"""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.msg_q: queue.Queue = queue.Queue()
        self.files: list[str] = []
        self.worker: threading.Thread | None = None
        self.running = False
        self.output_manual = False
        self.cancel_event = threading.Event()

        root.title(f"{APP_TITLE} v{APP_VERSION}")
        root.geometry("1080x760")
        root.minsize(940, 660)
        setup_style()
        self._build_ui()
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self._poll_queue()
        self.log("就绪。添加音频文件后点击「开始转换」。", "INFO")
        self.log("提示：首次运行会加载 basic-pitch 模型，可能需要几秒钟。", "INFO")

    # ---------- 界面构建 ----------
    def _build_ui(self) -> None:
        root = self.root

        header = ttk.Frame(root, padding=(14, 10))
        header.pack(fill="x")
        ttk.Label(header, text=APP_TITLE, font=("Microsoft YaHei UI", 16, "bold"),
                  foreground=GREEN).pack(side="left")
        ttk.Label(header, text="   basic-pitch 引擎 · 多线程 · 实时日志",
                  foreground=MUTED).pack(side="left", pady=(6, 0))
        self.env_btn = ttk.Button(header, text="环境检测", command=self.check_env)
        self.env_btn.pack(side="right")

        paned = ttk.PanedWindow(root, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        left = ttk.Frame(paned, padding=(0, 0, 8, 0))
        right = ttk.Frame(paned, padding=(8, 0, 0, 0))
        paned.add(left, weight=3)
        paned.add(right, weight=2)
        self._build_left(left)
        self._build_right(right)

        footer = ttk.Frame(root, padding=(12, 0, 12, 12))
        footer.pack(fill="x")
        self.start_btn = ttk.Button(footer, text="▶ 开始转换", style="Accent.TButton",
                                    width=14, command=self.start_convert)
        self.start_btn.pack(side="left")
        self.cancel_btn = ttk.Button(footer, text="■ 取消", width=10,
                                     state="disabled", command=self.cancel_convert)
        self.cancel_btn.pack(side="left", padx=8)
        ttk.Button(footer, text="清空日志", command=self.clear_log).pack(side="right", padx=6)
        ttk.Button(footer, text="打开输出目录", command=self.open_output).pack(side="right")

    def _build_left(self, parent: ttk.Frame) -> None:
        # 输入文件
        frm = ttk.LabelFrame(parent, text="① 输入音频（支持多选）", padding=8)
        frm.pack(fill="both", expand=True)
        bar = ttk.Frame(frm)
        bar.pack(fill="x")
        ttk.Button(bar, text="添加音频", command=self.add_files).pack(side="left")
        ttk.Button(bar, text="移除选中", command=self.remove_selected).pack(side="left", padx=6)
        ttk.Button(bar, text="清空列表", command=self.clear_files).pack(side="left")

        self.tree = ttk.Treeview(frm, columns=("name", "status", "path"),
                                 show="headings", height=8)
        self.tree.heading("name", text="文件名")
        self.tree.heading("status", text="状态")
        self.tree.heading("path", text="完整路径")
        self.tree.column("name", width=150, anchor="w")
        self.tree.column("status", width=64, anchor="center")
        self.tree.column("path", width=280, anchor="w")
        yscroll = ttk.Scrollbar(frm, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=yscroll.set)
        self.tree.pack(side="left", fill="both", expand=True, pady=(8, 0))
        yscroll.pack(side="right", fill="y", pady=(8, 0))

        # 输出目录
        out = ttk.LabelFrame(parent, text="② 输出目录", padding=8)
        out.pack(fill="x", pady=(10, 0))
        self.output_var = tk.StringVar(value="")
        ttk.Entry(out, textvariable=self.output_var).pack(side="left", fill="x", expand=True)
        ttk.Button(out, text="浏览...", command=self.browse_output).pack(side="left", padx=6)
        ttk.Label(out, text="留空则输出到每个音频所在目录，文件名与源文件相同（.mid）",
                  foreground=MUTED).pack(fill="x", pady=(6, 0))

        # 参数
        pf = ttk.LabelFrame(parent, text="③ 转换参数", padding=8)
        pf.pack(fill="x", pady=(10, 0))
        ttk.Label(pf, text="参数预设：").grid(row=0, column=0, sticky="w", pady=2)
        self.preset_var = tk.StringVar(value="通用")
        preset_combo = ttk.Combobox(pf, textvariable=self.preset_var,
                                    values=list(PRESETS), state="readonly", width=14)
        preset_combo.grid(row=0, column=1, sticky="w", pady=2)
        preset_combo.bind("<<ComboboxSelected>>", self.apply_preset)
        ttk.Label(pf, text="修改单项参数不会覆盖预设文件", foreground=MUTED).grid(
            row=0, column=2, sticky="w", padx=10)

        self.onset_var = tk.DoubleVar(value=0.50)
        self.frame_var = tk.DoubleVar(value=0.30)
        self.min_len_var = tk.DoubleVar(value=127.7)
        self.min_freq_var = tk.DoubleVar(value=0.0)
        self.max_freq_var = tk.DoubleVar(value=0.0)
        self.bpm_var = tk.IntVar(value=120)
        self.velocity_var = tk.IntVar(value=100)
        self.melodia_var = tk.BooleanVar(value=True)
        self.bends_var = tk.BooleanVar(value=False)

        self._make_scale(pf, 1, "起音阈值 (onset)", self.onset_var, 0.05, 0.95, 0.01, "{:.2f}")
        self._make_scale(pf, 2, "音符帧阈值 (frame)", self.frame_var, 0.05, 0.95, 0.01, "{:.2f}")
        self._make_spin(pf, 3, "最短音符 (毫秒)", self.min_len_var, 30, 1000, 10)
        self._make_spin(pf, 4, "最低频率 (Hz, 0=不限)", self.min_freq_var, 0, 5000, 10)
        self._make_spin(pf, 5, "最高频率 (Hz, 0=不限)", self.max_freq_var, 0, 12000, 100)
        self._make_spin(pf, 6, "MIDI 速度 (BPM)", self.bpm_var, 30, 300, 1)
        self._make_spin(pf, 7, "音符力度 (1-127)", self.velocity_var, 1, 127, 1)
        ttk.Checkbutton(pf, text="Melodia 后处理（人声推荐）",
                        variable=self.melodia_var).grid(row=8, column=0, columnspan=2,
                                                        sticky="w", pady=(6, 0))
        ttk.Checkbutton(pf, text="多重弯音（更细腻，文件更大）",
                        variable=self.bends_var).grid(row=8, column=2, sticky="w",
                                                      padx=10, pady=(6, 0))

    def _make_scale(self, parent, row, label, var, low, high, step, fmt) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=3)
        ttk.Scale(parent, from_=low, to=high, value=var.get(), variable=var,
                  orient="horizontal", length=180).grid(row=row, column=1, sticky="w")
        value_label = ttk.Label(parent, text=fmt.format(var.get()), width=7, foreground=ACCENT)
        value_label.grid(row=row, column=2, sticky="w", padx=10)
        var.trace_add("write", lambda *_: value_label.config(text=fmt.format(var.get())))

    def _make_spin(self, parent, row, label, var, low, high, step) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=3)
        ttk.Spinbox(parent, from_=low, to=high, increment=step, textvariable=var,
                    width=12).grid(row=row, column=1, sticky="w")

    def _build_right(self, parent: ttk.Frame) -> None:
        log_frame = ttk.LabelFrame(parent, text="④ 实时日志", padding=8)
        log_frame.pack(fill="both", expand=True)
        self.log_text = scrolledtext.ScrolledText(
            log_frame, wrap="word", height=16, bg=DARK, fg=TEXT,
            insertbackground=TEXT, font=("Microsoft YaHei UI", 9),
            relief="flat", borderwidth=0,
        )
        self.log_text.pack(fill="both", expand=True)
        self.log_text.configure(state="disabled")
        for tag, color in (("TIME", MUTED), ("INFO", TEXT), ("STEP", ACCENT),
                           ("SUCCESS", GREEN), ("WARN", YELLOW), ("ERROR", RED)):
            self.log_text.tag_configure(tag, foreground=color)

        prog_frame = ttk.Frame(parent, padding=(0, 10, 0, 0))
        prog_frame.pack(fill="x")
        self.status_var = tk.StringVar(value="就绪")
        ttk.Label(prog_frame, textvariable=self.status_var, font=FONT_BOLD).pack(anchor="w")
        self.progress = ttk.Progressbar(prog_frame, orient="horizontal",
                                        mode="determinate", maximum=100)
        self.progress.pack(fill="x", pady=7)
        self.progress_var = tk.StringVar(value="进度：0 / 0")
        ttk.Label(prog_frame, textvariable=self.progress_var,
                  foreground=MUTED).pack(anchor="w")

    # ---------- 日志与队列 ----------
    def log(self, text: str, level: str = "INFO") -> None:
        """线程安全：任何线程都可通过队列写日志。"""
        self.msg_q.put(("log", (str(text), level)))

    def _write_log(self, text: str, level: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{time.strftime('%H:%M:%S')}] ", "TIME")
        self.log_text.insert("end", text + "\n", level if level in
                             ("INFO", "STEP", "SUCCESS", "WARN", "ERROR") else "INFO")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def clear_log(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def _poll_queue(self) -> None:
        while True:
            try:
                kind, payload = self.msg_q.get_nowait()
            except queue.Empty:
                break
            self._handle_message(kind, payload)
        self.root.after(100, self._poll_queue)

    def _handle_message(self, kind: str, payload) -> None:
        if kind == "log":
            self._write_log(*payload)
        elif kind == "status":
            self.status_var.set(payload)
        elif kind == "progress":
            current, total = payload
            self.progress.configure(maximum=max(total, 1), value=current)
            self.progress_var.set(f"进度：{current} / {total}")
        elif kind == "rowstatus":
            self._update_row_status(*payload)
        elif kind == "ask_install":
            if messagebox.askyesno("缺少依赖", "未检测到可用的 basic-pitch。\n是否现在自动安装？（需要联网，过程可能较久）"):
                self._start_dependency_install()
        elif kind == "install_done":
            self.env_btn.configure(state="normal")
            if not self.running:
                self.start_btn.configure(state="normal")
        elif kind == "finished":
            self._on_finished(*payload)

    def _update_row_status(self, path: str, status: str) -> None:
        for item in self.tree.get_children():
            values = self.tree.item(item, "values")
            if len(values) >= 3 and values[2] == path:
                self.tree.item(item, values=(values[0], status, values[2]))
                break

    # ---------- 文件操作 ----------
    def add_files(self) -> None:
        paths = filedialog.askopenfilenames(title="选择音频文件", filetypes=AUDIO_FILE_TYPES)
        if not paths:
            return
        added = 0
        for raw in paths:
            path = Path(raw)
            if path.suffix.lower() not in SUPPORTED_EXT:
                self.log(f"跳过不支持的格式：{path.name}", "WARN")
                continue
            if not path.is_file():
                self.log(f"文件不存在：{path}", "WARN")
                continue
            if str(path) in self.files:
                self.log(f"已在列表中，跳过：{path.name}", "WARN")
                continue
            self.files.append(str(path))
            self.tree.insert("", "end", values=(path.name, "待转换", str(path)))
            added += 1
        if added:
            self.log(f"已添加 {added} 个音频文件。", "SUCCESS")
            if not self.output_manual and not self.output_var.get().strip():
                self.output_var.set(str(Path(paths[0]).parent))
                self.log("输出目录自动设为第一个音频所在目录。", "INFO")

    def remove_selected(self) -> None:
        selected = self.tree.selection()
        if not selected:
            messagebox.showinfo(APP_TITLE, "请先选中要移除的文件。")
            return
        for item in selected:
            path = self.tree.item(item, "values")[2]
            if path in self.files:
                self.files.remove(path)
            self.tree.delete(item)
        self.log(f"已移除 {len(selected)} 个文件。", "INFO")

    def clear_files(self) -> None:
        if self.running:
            messagebox.showwarning(APP_TITLE, "转换进行中，不能清空列表。")
            return
        self.files.clear()
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.log("已清空文件列表。", "INFO")

    def browse_output(self) -> None:
        directory = filedialog.askdirectory(title="选择输出目录")
        if directory:
            self.output_var.set(directory)
            self.output_manual = True

    def open_output(self) -> None:
        target = self.output_var.get().strip() or (
            str(Path(self.files[0]).parent) if self.files else str(Path.home())
        )
        if not Path(target).exists():
            messagebox.showinfo(APP_TITLE, f"目录尚不存在：\n{target}")
            return
        try:
            if os.name == "nt":
                os.startfile(target)  # noqa: S606
            elif sys.platform == "darwin":
                subprocess.run(["open", target], check=False)
            else:
                subprocess.run(["xdg-open", target], check=False)
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"无法打开目录：{exc}")

    def apply_preset(self, _event=None) -> None:
        preset = PRESETS.get(self.preset_var.get())
        if not preset:
            return
        self.onset_var.set(preset["onset"])
        self.frame_var.set(preset["frame"])
        self.min_len_var.set(preset["min_len"])
        self.min_freq_var.set(preset["min_freq"])
        self.max_freq_var.set(preset["max_freq"])
        self.bpm_var.set(preset["bpm"])
        self.velocity_var.set(preset["velocity"])
        self.melodia_var.set(preset["melodia"])
        self.bends_var.set(preset["bends"])
        self.log(f"已应用「{self.preset_var.get()}」参数预设。", "INFO")

    # ---------- 转换流程 ----------
    def collect_params(self) -> dict:
        min_freq = float(self.min_freq_var.get())
        max_freq = float(self.max_freq_var.get())
        return {
            "onset_threshold": float(self.onset_var.get()),
            "frame_threshold": float(self.frame_var.get()),
            "minimum_note_length": float(self.min_len_var.get()),
            "minimum_frequency": min_freq if min_freq > 0 else None,
            "maximum_frequency": max_freq if max_freq > 0 else None,
            "midi_tempo": float(self.bpm_var.get()),
            "velocity": int(self.velocity_var.get()),
            "melodia_trick": bool(self.melodia_var.get()),
            "multiple_pitch_bends": bool(self.bends_var.get()),
        }

    def start_convert(self) -> None:
        if self.running:
            return
        if not self.files:
            messagebox.showwarning(APP_TITLE, "请先添加音频文件。")
            return
        output_dir = self.output_var.get().strip() or None
        if output_dir:
            try:
                Path(output_dir).mkdir(parents=True, exist_ok=True)
            except Exception as exc:
                messagebox.showerror(APP_TITLE, f"无法创建输出目录：\n{exc}")
                return

        self.cancel_event.clear()
        self.running = True
        self.start_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")
        self.status_var.set("正在初始化引擎...")
        self.progress.configure(maximum=len(self.files), value=0)
        self.progress_var.set(f"进度：0 / {len(self.files)}")
        for item in self.tree.get_children():
            values = self.tree.item(item, "values")
            self.tree.item(item, values=(values[0], "待转换", values[2]))

        self.worker = ConvertWorker(self, list(self.files), output_dir, self.collect_params())
        self.worker.start()

    def cancel_convert(self) -> None:
        if self.running:
            self.cancel_event.set()
            self.cancel_btn.configure(state="disabled")
            self.log("已请求取消，将在当前文件转换完成后停止。", "WARN")

    def _on_finished(self, success: int, failed: int, cancelled: bool) -> None:
        self.running = False
        self.start_btn.configure(state="normal")
        self.cancel_btn.configure(state="disabled")
        self.status_var.set("已取消" if cancelled else "转换完成")
        self.log(f"转换结束：成功 {success} 个，失败 {failed} 个"
                 + ("（已取消）" if cancelled else ""),
                 "WARN" if (cancelled or failed) else "SUCCESS")
        messagebox.showinfo(APP_TITLE,
                            f"转换结束\n\n成功：{success}\n失败：{failed}"
                            + ("\n状态：已取消" if cancelled else ""))

    # ---------- 环境检测与依赖安装 ----------
    def check_env(self) -> None:
        self.env_btn.configure(state="disabled")
        self.log("正在检测运行环境...", "STEP")
        self.msg_q.put(("status", "正在检测运行环境..."))
        CheckWorker(self).start()

    def _start_dependency_install(self) -> None:
        self.env_btn.configure(state="disabled")
        self.running = True
        self.start_btn.configure(state="disabled")
        self.cancel_event.clear()
        DependencyWorker(self).start()

    def on_close(self) -> None:
        if self.running and not messagebox.askokcancel("退出", "任务正在进行中，确定要退出吗？"):
            return
        self.cancel_event.set()
        self.root.destroy()

    # ---------- 入口 ----------
    def run(self) -> None:
        self.root.mainloop()


class ConvertWorker(threading.Thread):
    """在后台线程执行模型推理；只通过队列与主线程通信。"""

    def __init__(self, app: App, files: list[str], output_dir: str | None, params: dict) -> None:
        super().__init__(daemon=True)
        self.app = app
        self.files = files
        self.output_dir = output_dir
        self.params = params

    def run(self) -> None:
        success = failed = 0
        cancelled = False
        total = len(self.files)
        try:
            self.app.log("正在加载 basic-pitch 模型...", "STEP")
            from basic_pitch.inference import ICASSP_2022_MODEL_PATH, Model, predict

            model = Model(ICASSP_2022_MODEL_PATH)
            self.app.log("模型加载完成，开始逐文件转换。", "SUCCESS")

            for index, audio in enumerate(self.files, start=1):
                if self.app.cancel_event.is_set():
                    cancelled = True
                    break
                name = Path(audio).name
                self.app.log(f"[{index}/{total}] 正在转换：{name}", "STEP")
                self.app.msg_q.put(("status", f"正在转换 {index}/{total}：{name}"))
                try:
                    _, midi_data, note_events = predict(
                        audio,
                        model_or_model_path=model,
                        onset_threshold=self.params["onset_threshold"],
                        frame_threshold=self.params["frame_threshold"],
                        minimum_note_length=self.params["minimum_note_length"],
                        minimum_frequency=self.params["minimum_frequency"],
                        maximum_frequency=self.params["maximum_frequency"],
                        multiple_pitch_bends=self.params["multiple_pitch_bends"],
                        melodia_trick=self.params["melodia_trick"],
                        midi_tempo=self.params["midi_tempo"],
                    )
                    for instrument in midi_data.instruments:
                        for note in instrument.notes:
                            note.velocity = self.params["velocity"]

                    dst_dir = Path(self.output_dir) if self.output_dir else Path(audio).parent
                    dst_dir.mkdir(parents=True, exist_ok=True)
                    out_path = dst_dir / (Path(audio).stem + ".mid")
                    midi_data.write(str(out_path))
                    success += 1
                    self.app.log(f"完成：{out_path.name}（识别 {len(note_events)} 个音符）", "SUCCESS")
                    self.app.msg_q.put(("rowstatus", (audio, "成功")))
                except Exception as exc:
                    failed += 1
                    self.app.log(f"转换失败：{name} → {exc}", "ERROR")
                    self.app.log(traceback.format_exc(), "ERROR")
                    self.app.msg_q.put(("rowstatus", (audio, "失败")))
                finally:
                    self.app.msg_q.put(("progress", (index, total)))
        except Exception as exc:
            failed += len(self.files) - success
            self.app.log(f"引擎初始化失败：{exc}", "ERROR")
            self.app.log(traceback.format_exc(), "ERROR")
        finally:
            self.app.msg_q.put(("finished", (success, failed, cancelled)))


class CheckWorker(threading.Thread):
    """后台检测依赖与模型，避免阻塞界面。"""

    def __init__(self, app: App) -> None:
        super().__init__(daemon=True)
        self.app = app

    def run(self) -> None:
        try:
            import basic_pitch  # noqa: F401
            try:
                version = metadata.version("basic-pitch")
            except metadata.PackageNotFoundError:
                version = "未知版本"
            self.app.log(f"Python：{sys.version.split()[0]}（{sys.executable}）", "INFO")
            self.app.log(f"basic-pitch：{version}，已安装", "SUCCESS")
            from basic_pitch.inference import ICASSP_2022_MODEL_PATH
            model_file = Path(ICASSP_2022_MODEL_PATH) / "saved_model.pb"
            if model_file.exists():
                self.app.log(f"模型文件：完整（{ICASSP_2022_MODEL_PATH}）", "SUCCESS")
            else:
                self.app.log("模型文件缺失，首次转换时将自动下载。", "WARN")
            try:
                import tensorflow as tf
                self.app.log(f"TensorFlow：{tf.__version__}", "INFO")
            except Exception:
                self.app.log("TensorFlow 未能导入，转换可能无法进行。", "WARN")
        except Exception as exc:
            self.app.log(f"环境检测失败：{exc}", "ERROR")
            self.app.msg_q.put(("ask_install", None))
        finally:
            self.app.msg_q.put(("install_done", None))
            self.app.msg_q.put(("status", "就绪"))


class DependencyWorker(threading.Thread):
    """后台执行 pip 安装，逐行转发输出到日志面板。"""

    def __init__(self, app: App) -> None:
        super().__init__(daemon=True)
        self.app = app

    def run(self) -> None:
        cmd = [sys.executable, "-m", "pip", "install", "basic-pitch"]
        self.app.log("开始安装依赖：" + " ".join(cmd), "STEP")
        self.app.msg_q.put(("status", "正在安装依赖，请稍候..."))
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", bufsize=1,
                creationflags=flags,
            )
            assert proc.stdout is not None
            for line in proc.stdout:
                if self.app.cancel_event.is_set():
                    proc.terminate()
                    self.app.log("用户取消了依赖安装。", "WARN")
                    break
                line = line.rstrip()
                if line:
                    self.app.log(line, "INFO")
            returncode = proc.wait()
            if returncode == 0:
                self.app.log("依赖安装完成，可以开始转换。", "SUCCESS")
            else:
                self.app.log(f"依赖安装失败，退出码：{returncode}", "ERROR")
        except Exception as exc:
            self.app.log(f"依赖安装出错：{exc}", "ERROR")
            self.app.log(traceback.format_exc(), "ERROR")
        finally:
            self.app.running = False
            self.app.msg_q.put(("install_done", None))
            self.app.msg_q.put(("status", "就绪"))


def main() -> None:
    if os.name == "nt":
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    root = tk.Tk()
    app = App(root)
    app.run()


if __name__ == "__main__":
    main()
