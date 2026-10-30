"""桌面图形界面（tkinter，零第三方依赖）。

启动：
    memoir gui
或：
    python -m memoir.desktop

设计取向：
- 用标准库 tkinter，不引入 Qt/Electron，装好 Python 就能开
- 复用 memoir 已有的 storage / review / persona，不重写业务逻辑
- 模型调用放后台线程，界面不卡
"""

from __future__ import annotations

import queue
import sys
import threading
import tkinter as tk
from datetime import date
from tkinter import messagebox, ttk
from typing import Any, Callable

from .config import Config
from .i18n import I18N
from .models import KINDS
from .persona import distill, render_profile
from .review import generate_review, render_review
from .storage import Store

APP_TITLE = "memoir · 记忆"

KIND_LABEL = {
    "event": "事",
    "thought": "想",
    "feeling": "情",
    "note": "注",
}

COLORS = {
    "bg": "#f6f7f9",
    "panel": "#ffffff",
    "ink": "#1f2328",
    "muted": "#6b7280",
    "line": "#e5e7eb",
    "accent": "#2563eb",
    "accent_dark": "#1d4ed8",
    "danger": "#b42318",
}


def _enable_dpi_awareness() -> None:
    if sys.platform != "win32":
        return
    try:
        from ctypes import windll

        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:  # noqa: BLE001
        pass


class MemoirApp(tk.Tk):
    def __init__(self, cfg: Config) -> None:
        _enable_dpi_awareness()
        super().__init__()
        self.cfg = cfg
        self.i18n = I18N(cfg.lang)
        self.store = Store(cfg.db_path)
        self._work: queue.Queue[tuple[str, Any]] = queue.Queue()
        self._busy = False

        self.title(APP_TITLE)
        self.geometry("1000x700")
        self.minsize(820, 560)
        self.configure(bg=COLORS["bg"])
        self._setup_style()
        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(120, self._drain_queue)
        self._refresh_all()

    # ---------------- 样式 ----------------
    def _setup_style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        base = ("Microsoft YaHei UI", 10) if sys.platform == "win32" else ("Helvetica", 11)
        style.configure(".", font=base, background=COLORS["bg"], foreground=COLORS["ink"])
        style.configure("TFrame", background=COLORS["bg"])
        style.configure("Panel.TFrame", background=COLORS["panel"])
        style.configure("TLabel", background=COLORS["bg"], foreground=COLORS["ink"])
        style.configure("Muted.TLabel", foreground=COLORS["muted"])
        style.configure("Title.TLabel", font=(base[0], 15, "bold"))
        style.configure("TButton", padding=(12, 6))
        style.configure("Accent.TButton", foreground="#ffffff", background=COLORS["accent"])
        style.map("Accent.TButton", background=[("active", COLORS["accent_dark"])])
        style.configure("TNotebook", background=COLORS["bg"], borderwidth=0)
        style.configure("TNotebook.Tab", padding=(18, 8))
        style.configure("Treeview", rowheight=28, fieldbackground=COLORS["panel"], background=COLORS["panel"])
        style.configure("Treeview.Heading", font=(base[0], 10, "bold"))

    # ---------------- 布局 ----------------
    def _build_ui(self) -> None:
        header = ttk.Frame(self, padding=(18, 14, 18, 6))
        header.pack(fill="x")
        ttk.Label(header, text=APP_TITLE, style="Title.TLabel").pack(side="left")
        self.status = ttk.Label(header, text="", style="Muted.TLabel")
        self.status.pack(side="right")

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=14, pady=(0, 12))

        self.tab_today = ttk.Frame(self.nb, padding=14)
        self.tab_review = ttk.Frame(self.nb, padding=14)
        self.tab_persona = ttk.Frame(self.nb, padding=14)
        self.tab_search = ttk.Frame(self.nb, padding=14)
        self.tab_settings = ttk.Frame(self.nb, padding=14)

        self.nb.add(self.tab_today, text="  今天  ")
        self.nb.add(self.tab_review, text="  复盘  ")
        self.nb.add(self.tab_persona, text="  人格  ")
        self.nb.add(self.tab_search, text="  搜索  ")
        self.nb.add(self.tab_settings, text="  设置  ")

        self._build_today()
        self._build_review()
        self._build_persona()
        self._build_search()
        self._build_settings()

    # ---- 今天 ----
    def _build_today(self) -> None:
        top = ttk.Frame(self.tab_today)
        top.pack(fill="x")
        self.kind_var = tk.StringVar(value="event")
        kinds = ttk.Combobox(
            top, textvariable=self.kind_var, width=6, state="readonly",
            values=list(KINDS),
        )
        kinds.pack(side="left")
        self.entry = tk.Text(top, height=3, wrap="word", relief="solid", borderwidth=1,
                             font=("Microsoft YaHei UI", 11), undo=True)
        self.entry.pack(side="left", fill="x", expand=True, padx=10)
        self.entry.bind("<Control-Return>", lambda e: (self._add_entry(), "break")[1])
        btn = ttk.Button(top, text="记下  Ctrl+Enter", style="Accent.TButton", command=self._add_entry)
        btn.pack(side="left")

        ttk.Label(
            self.tab_today,
            text="类型：event 事件 / thought 想法 / feeling 情绪 / note 备注",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(6, 10))

        wrap = ttk.Frame(self.tab_today)
        wrap.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(wrap, columns=("time", "kind", "text"), show="headings", height=14)
        self.tree.heading("time", text="时间")
        self.tree.heading("kind", text="类型")
        self.tree.heading("text", text="内容")
        self.tree.column("time", width=70, anchor="center", stretch=False)
        self.tree.column("kind", width=60, anchor="center", stretch=False)
        self.tree.column("text", width=640, anchor="w")
        sb = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        bottom = ttk.Frame(self.tab_today)
        bottom.pack(fill="x", pady=(10, 0))
        ttk.Button(bottom, text="删除选中", command=self._delete_selected).pack(side="left")
        ttk.Button(bottom, text="刷新", command=self._refresh_today).pack(side="left", padx=8)
        self.today_count = ttk.Label(bottom, text="", style="Muted.TLabel")
        self.today_count.pack(side="right")

    # ---- 复盘 ----
    def _build_review(self) -> None:
        bar = ttk.Frame(self.tab_review)
        bar.pack(fill="x")
        ttk.Label(bar, text="日期").pack(side="left")
        self.review_date = tk.StringVar(value=date.today().isoformat())
        ttk.Entry(bar, textvariable=self.review_date, width=14).pack(side="left", padx=8)
        self.offline_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(bar, text="不连模型（本地摘要）", variable=self.offline_var).pack(side="left")
        ttk.Button(bar, text="生成复盘", style="Accent.TButton", command=self._run_review).pack(side="right")

        self.review_text = tk.Text(
            self.tab_review, wrap="word", relief="flat", padx=18, pady=14,
            font=("Microsoft YaHei UI", 11), bg=COLORS["panel"], state="disabled",
        )
        self.review_text.pack(fill="both", expand=True, pady=(12, 0))

    # ---- 人格 ----
    def _build_persona(self) -> None:
        bar = ttk.Frame(self.tab_persona)
        bar.pack(fill="x")
        ttk.Button(bar, text="从最近复盘学习", style="Accent.TButton", command=self._run_distill).pack(side="left")
        ttk.Button(bar, text="刷新", command=self._refresh_persona).pack(side="left", padx=8)
        self.persona_text = tk.Text(
            self.tab_persona, wrap="word", relief="flat", padx=18, pady=14,
            font=("Microsoft YaHei UI", 11), bg=COLORS["panel"], state="disabled",
        )
        self.persona_text.pack(fill="both", expand=True, pady=(12, 0))

    # ---- 搜索 ----
    def _build_search(self) -> None:
        bar = ttk.Frame(self.tab_search)
        bar.pack(fill="x")
        self.query = tk.StringVar()
        ent = ttk.Entry(bar, textvariable=self.query)
        ent.pack(side="left", fill="x", expand=True)
        ent.bind("<Return>", lambda e: self._do_search())
        ttk.Button(bar, text="搜索", style="Accent.TButton", command=self._do_search).pack(side="left", padx=8)

        wrap = ttk.Frame(self.tab_search)
        wrap.pack(fill="both", expand=True, pady=(12, 0))
        self.search_tree = ttk.Treeview(wrap, columns=("day", "kind", "text"), show="headings")
        for col, text, w, anchor in (("day", "日期", 110, "center"), ("kind", "类型", 70, "center"), ("text", "内容", 620, "w")):
            self.search_tree.heading(col, text=text)
            self.search_tree.column(col, width=w, anchor=anchor, stretch=(col == "text"))
        sb = ttk.Scrollbar(wrap, orient="vertical", command=self.search_tree.yview)
        self.search_tree.configure(yscrollcommand=sb.set)
        self.search_tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

    # ---- 设置 ----
    def _build_settings(self) -> None:
        grid = ttk.Frame(self.tab_settings)
        grid.pack(fill="x", anchor="nw")
        self.set_vars: dict[str, tk.StringVar] = {
            "base_url": tk.StringVar(value=self.cfg.model.base_url),
            "name": tk.StringVar(value=self.cfg.model.name),
            "api_key": tk.StringVar(value=self.cfg.model.api_key),
            "temperature": tk.StringVar(value=str(self.cfg.model.temperature)),
            "max_tokens": tk.StringVar(value=str(self.cfg.model.max_tokens)),
            "timeout": tk.StringVar(value=str(self.cfg.model.timeout)),
            "lang": tk.StringVar(value=self.cfg.lang),
        }
        rows = [
            ("接口地址", "base_url"),
            ("模型名", "name"),
            ("API Key", "api_key"),
            ("temperature", "temperature"),
            ("max_tokens", "max_tokens"),
            ("超时(秒)", "timeout"),
        ]
        for idx, (label, key) in enumerate(rows):
            ttk.Label(grid, text=label).grid(row=idx, column=0, sticky="w", pady=6, padx=(0, 12))
            ttk.Entry(grid, textvariable=self.set_vars[key], width=52).grid(row=idx, column=1, sticky="w", pady=6)
        ttk.Label(grid, text="界面语言").grid(row=len(rows), column=0, sticky="w", pady=6)
        ttk.Combobox(
            grid, textvariable=self.set_vars["lang"], state="readonly", width=8,
            values=["zh", "en", "ja", "ko"],
        ).grid(row=len(rows), column=1, sticky="w", pady=6)

        bar = ttk.Frame(self.tab_settings)
        bar.pack(fill="x", pady=14)
        ttk.Button(bar, text="保存配置", style="Accent.TButton", command=self._save_settings).pack(side="left")
        ttk.Button(bar, text="测试模型连接", command=self._test_model).pack(side="left", padx=8)

        self.settings_hint = ttk.Label(self.tab_settings, text="", style="Muted.TLabel")
        self.settings_hint.pack(anchor="w")

        info = ttk.Label(
            self.tab_settings,
            text=f"数据目录：{self.cfg.home}",
            style="Muted.TLabel",
        )
        info.pack(anchor="w", pady=(16, 0))

    # ---------------- 后台任务 ----------------
    def _run_bg(self, label: str, fn: Callable[[], Any], done: Callable[[Any], None]) -> None:
        if self._busy:
            return
        self._busy = True
        self._set_status(f"{label}…")

        def worker() -> None:
            try:
                result = fn()
                self._work.put(("ok", (done, result)))
            except Exception as exc:  # noqa: BLE001
                self._work.put(("err", exc))

        threading.Thread(target=worker, daemon=True).start()

    def _drain_queue(self) -> None:
        try:
            while True:
                kind, payload = self._work.get_nowait()
                self._busy = False
                if kind == "ok":
                    done, result = payload
                    self._set_status("")
                    done(result)
                else:
                    self._set_status("")
                    messagebox.showerror("出错了", str(payload))
        except queue.Empty:
            pass
        self.after(120, self._drain_queue)

    def _set_status(self, text: str) -> None:
        self.status.configure(text=text)

    # ---------------- 动作 ----------------
    def _add_entry(self) -> None:
        text = self.entry.get("1.0", "end").strip()
        if not text:
            return
        self.store.add_entry(text=text, kind=self.kind_var.get(), source="desktop")
        self.entry.delete("1.0", "end")
        self._refresh_today()

    def _delete_selected(self) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        if not messagebox.askyesno("确认删除", "删除后无法恢复，确定？"):
            return
        for item in sel:
            entry_id = int(self.tree.item(item, "tags")[0])
            self.store.delete_entry(entry_id)
        self._refresh_today()

    def _refresh_today(self) -> None:
        day = date.today().isoformat()
        entries = self.store.entries_for_day(day)
        self.tree.delete(*self.tree.get_children())
        for e in entries:
            stamp = e.ts[11:16] if len(e.ts) >= 16 else e.ts
            self.tree.insert(
                "", "end",
                values=(stamp, KIND_LABEL.get(e.kind, e.kind), e.text),
                tags=(str(e.id),),
            )
        self.today_count.configure(text=f"今天 {len(entries)} 条")
        stats = self.store.stats()
        self._set_status(f"共 {stats['entries']} 条 · {stats['days']} 天 · {stats['reviews']} 份复盘")

    def _run_review(self) -> None:
        day = self.review_date.get().strip() or date.today().isoformat()
        offline = self.offline_var.get()

        def work() -> Any:
            return generate_review(self.store, self.cfg, self.i18n, day=day, offline=offline)

        def done(review: Any) -> None:
            if review is None:
                self._write_text(self.review_text, f"{day} 没有记录，跳过。")
                return
            body = render_review(review, self.i18n)
            if review.isolated:
                body += f"\n提示：{review.isolated} 条记录疑似含指令性文本，已隔离。\n"
            if review.dropped:
                body += "\n提示：本次复盘疑似被指令带偏，已丢弃。\n"
            self._write_text(self.review_text, body)
            self._refresh_today()

        self._run_bg("生成复盘", work, done)

    def _run_distill(self) -> None:
        def work() -> Any:
            return distill(self.store, self.cfg, self.i18n, days=7)

        def done(learned: Any) -> None:
            self._write_text(
                self.persona_text,
                f"本次学到 {len(learned)} 条观察。\n\n" + render_profile(self.store, self.i18n),
            )

        self._run_bg("学习中", work, done)

    def _refresh_persona(self) -> None:
        self._write_text(self.persona_text, render_profile(self.store, self.i18n))

    def _do_search(self) -> None:
        q = self.query.get().strip()
        if not q:
            return
        hits = self.store.search(q, limit=100)
        self.search_tree.delete(*self.search_tree.get_children())
        for e in hits:
            self.search_tree.insert(
                "", "end",
                values=(e.day, KIND_LABEL.get(e.kind, e.kind), e.text),
            )

    def _save_settings(self) -> None:
        try:
            self.cfg.model.base_url = self.set_vars["base_url"].get().strip()
            self.cfg.model.name = self.set_vars["name"].get().strip()
            self.cfg.model.api_key = self.set_vars["api_key"].get().strip()
            self.cfg.model.temperature = float(self.set_vars["temperature"].get())
            self.cfg.model.max_tokens = int(self.set_vars["max_tokens"].get())
            self.cfg.model.timeout = int(self.set_vars["timeout"].get())
            self.cfg.lang = self.set_vars["lang"].get()
            self.cfg.save()
            self.i18n = I18N(self.cfg.lang)
            self.settings_hint.configure(text=f"已保存到 {self.cfg.config_path}")
        except ValueError as exc:
            messagebox.showerror("配置不合法", str(exc))

    def _test_model(self) -> None:
        from .llm import LLMClient

        self._save_settings()
        client = LLMClient(self.cfg.model)

        def work() -> Any:
            return client.health()

        def done(result: Any) -> None:
            ok, detail = result
            self.settings_hint.configure(text=("可用：" if ok else "不可用：") + str(detail)[:120])

        self._run_bg("测试连接", work, done)

    def _write_text(self, widget: tk.Text, content: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", content)
        widget.configure(state="disabled")

    def _refresh_all(self) -> None:
        self._refresh_today()
        self._refresh_persona()

    def _on_close(self) -> None:
        try:
            self.store.close()
        finally:
            self.destroy()


def main(argv: list[str] | None = None) -> int:
    cfg = Config.load()
    cfg.ensure_dirs()
    app = MemoirApp(cfg)
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
