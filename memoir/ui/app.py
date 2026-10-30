"""深色主题桌面界面。

布局：左导航 220 / 主区自适应 / 右参数栏 280。
所有卡片、按钮、导航项都是自绘 Canvas —— tkinter 原生控件没有圆角。
"""

from __future__ import annotations

import queue
import sys
import threading
import tkinter as tk
from datetime import date
from typing import Any, Callable

from .. import __version__
from ..config import Config
from ..i18n import I18N
from ..models import KINDS
from ..persona import distill, render_profile
from ..review import generate_review, render_review
from ..storage import Store
from . import theme as T
from .widgets import (Card, Chip, FlatButton, HairLine, NavItem, ScalePattern,
                      StatRow, round_rect)

PAGES = [
    ("memory", "记忆库", "lib"),
    ("review", "复盘记录", "review"),
    ("persona", "人格档案", "person"),
    ("settings", "设置", "gear"),
    ("plugins", "插件", "plugin"),
]


def _dpi_aware() -> None:
    if sys.platform != "win32":
        return
    try:
        from ctypes import windll

        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:  # noqa: BLE001
        pass


class MemoryList(tk.Canvas):
    """记忆列表：整块 Canvas 自绘，行高固定，支持滚动 / 悬浮 / 选中。"""

    ROW_H = 76
    CARD_H = 64

    def __init__(self, master: tk.Misc, on_select: Callable[[int | None], None]):
        super().__init__(master, bg=T.BG_BASE, highlightthickness=0, bd=0)
        self._entries: list[Any] = []
        self._selected: int | None = None
        self._hover: int | None = None
        self._on_select = on_select
        self.bind("<Configure>", lambda e: self._draw())
        self.bind_all("<MouseWheel>", self._on_wheel)
        self.bind("<Button-1>", self._on_click)
        self.bind("<Motion>", self._on_motion)
        self.bind("<Leave>", lambda e: self._set_hover(None))

    def set_entries(self, entries: list[Any]) -> None:
        self._entries = entries
        self._selected = None
        self._draw()
        self.yview_moveto(0)

    def selected_entry(self) -> Any | None:
        if self._selected is None or self._selected >= len(self._entries):
            return None
        return self._entries[self._selected]

    def _on_wheel(self, event: tk.Event) -> None:
        if self.winfo_containing(event.x_root, event.y_root) is not self:
            return
        self.yview_scroll(int(-event.delta / 120), "units")

    def _row_at(self, y: int) -> int | None:
        idx = int(self.canvasy(y) // self.ROW_H)
        return idx if 0 <= idx < len(self._entries) else None

    def _on_click(self, event: tk.Event) -> None:
        idx = self._row_at(event.y)
        self._selected = idx
        self._draw()
        self._on_select(idx)

    def _on_motion(self, event: tk.Event) -> None:
        self._set_hover(self._row_at(event.y))

    def _set_hover(self, idx: int | None) -> None:
        if idx != self._hover:
            self._hover = idx
            self._draw()

    def _draw(self) -> None:
        self.delete("all")
        w = self.winfo_width() or 700
        total = max(self.ROW_H * max(1, len(self._entries)), self.winfo_height() or 1)
        self.configure(scrollregion=(0, 0, w, total))
        if not self._entries:
            self.create_text(w / 2, 120, text="还没有记录。上面写一句试试。",
                             fill=T.INK_3, font=T.F(13))
            return
        y = 0
        for i, e in enumerate(self._entries):
            self._draw_row(y, w, i, e)
            y += self.ROW_H

    def _draw_row(self, y: int, w: int, i: int, e: Any) -> None:
        sel = i == self._selected
        hov = i == self._hover
        fill = T.GLOW if sel else (T.BG_CARD_HOVER if hov else T.BG_CARD)
        border = T.SOFT if sel else T.LINE_HAIR
        round_rect(self, 0, y, w - 2, y + self.CARD_H, T.CARD_R,
                   fill=fill, outline=border, width=1)
        cy = y + self.CARD_H / 2

        # 时间块
        stamp = e.ts[11:16] if len(e.ts) >= 16 else e.ts
        self.create_text(78, cy, text=stamp, anchor="e", fill=T.INK_3, font=T.F(12, family="mono"))
        self.create_line(98, cy - 12, 98, cy + 12, fill=T.LINE_HAIR)
        # 类型块
        kc = T.KIND_COLORS.get(e.kind, T.INK_2)
        self.create_oval(114, cy - 3, 120, cy + 3, fill=kc, outline="")
        self.create_text(128, cy, text=T.KIND_LABEL.get(e.kind, e.kind), anchor="w",
                         fill=T.INK_2, font=T.F(12))
        self.create_line(172, cy - 12, 172, cy + 12, fill=T.LINE_HAIR)
        # 内容块
        body = e.text if len(e.text) <= 46 else e.text[:46] + "…"
        self.create_text(192, cy, text=body, anchor="w", fill=T.INK, font=T.F(15, family="serif"))


class MemoirApp(tk.Tk):
    def __init__(self, cfg: Config) -> None:
        _dpi_aware()
        super().__init__()
        self.cfg = cfg
        self.i18n = I18N(cfg.lang)
        self.store = Store(cfg.db_path)
        self._work: queue.Queue[tuple[str, Any]] = queue.Queue()
        self._busy = False
        self._page = "memory"
        self._navs: dict[str, NavItem] = {}

        self.title(f"memoir · 记忆   v{__version__}")
        self.geometry("1280x800")
        self.minsize(1080, 680)
        self.configure(bg=T.BG_BASE)
        try:
            self.tk.call("tk", "scaling", 1.0)
        except tk.TclError:
            pass

        self._build_layout()
        self._build_sidebar()
        self._build_main()
        self._build_panel()
        self._show_page("memory")
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(120, self._drain_queue)

    # ---------------- 布局 ----------------
    def _build_layout(self) -> None:
        self.sidebar = tk.Frame(self, bg=T.BG_SIDE, width=T.SIDEBAR_W)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        self.main = tk.Frame(self, bg=T.BG_BASE)
        self.main.pack(side="left", fill="both", expand=True)

        self.panel = tk.Frame(self, bg=T.BG_PANEL, width=T.PANEL_W)
        self.panel.pack(side="right", fill="y")
        self.panel.pack_propagate(False)

    # ---------------- 侧栏 ----------------
    def _build_sidebar(self) -> None:
        head = tk.Frame(self.sidebar, bg=T.BG_SIDE, height=110)
        head.pack(fill="x")
        head.pack_propagate(False)
        tk.Label(head, text="memoir", bg=T.BG_SIDE, fg=T.INK,
                 font=T.F(17, "bold")).place(x=24, y=26)
        tk.Label(head, text="记忆", bg=T.BG_SIDE, fg=T.INK_3,
                 font=T.F(12)).place(x=24, y=52)

        for key, label, icon in PAGES:
            item = NavItem(self.sidebar, label, icon, lambda k=key: self._show_page(k))
            item.pack(fill="x")
            self._navs[key] = item

        HairLine(self.sidebar, parent_bg=T.BG_SIDE).pack(fill="x", padx=16, pady=(18, 10))

        status = tk.Frame(self.sidebar, bg=T.BG_SIDE)
        status.pack(fill="x", padx=16)
        self._dot = tk.Canvas(status, width=10, height=10, bg=T.BG_SIDE,
                              highlightthickness=0, bd=0)
        self._dot.pack(side="left")
        self._dot.create_oval(1, 1, 9, 9, fill=T.CYAN, outline="")
        self._status = tk.Label(status, text="模型已连接", bg=T.BG_SIDE, fg=T.INK_2,
                                font=T.F(12))
        self._status.pack(side="left", padx=(8, 0))

        spacer = tk.Frame(self.sidebar, bg=T.BG_SIDE)
        spacer.pack(fill="both", expand=True)
        ScalePattern(spacer).pack(side="bottom", anchor="w", padx=4, pady=8)

    # ---------------- 主区 ----------------
    def _build_main(self) -> None:
        top = tk.Frame(self.main, bg=T.BG_BASE, height=T.TOPBAR_H)
        top.pack(fill="x")
        top.pack_propagate(False)
        self._title = tk.Label(top, text="记忆库", bg=T.BG_BASE, fg=T.INK, font=T.F(20, "bold"))
        self._title.place(x=T.PAD, y=13)

        search_wrap = tk.Frame(top, bg=T.BG_INPUT, highlightthickness=1,
                               highlightbackground=T.LINE_HAIR, highlightcolor=T.CYAN)
        search_wrap.place(relx=1.0, x=-64, y=12, width=232, height=32, anchor="ne")
        search_wrap.pack_propagate(False)
        tk.Label(search_wrap, text="⌕", bg=T.BG_CARD, fg=T.INK_3,
                 font=T.F(14)).pack(side="left", padx=(10, 4))
        self._search = tk.Entry(search_wrap, bg=T.BG_INPUT, fg=T.INK_3, relief="flat",
                                insertbackground=T.CYAN, font=T.F(12),
                                highlightthickness=0, bd=0)
        self._search.pack(side="left", fill="both", expand=True, padx=(0, 8))
        self._search.insert(0, "搜索记忆…")
        self._search_on = True

        def _search_in(_e: object) -> None:
            if self._search_on:
                self._search.delete(0, "end")
                self._search.configure(fg=T.INK)
                self._search_on = False

        def _search_out(_e: object) -> None:
            if not self._search.get().strip():
                self._search.insert(0, "搜索记忆…")
                self._search.configure(fg=T.INK_3)
                self._search_on = True

        self._search.bind("<FocusIn>", _search_in)
        self._search.bind("<FocusOut>", _search_out)
        self._search.bind("<Return>", lambda e: self._do_search())

        HairLine(self.main, parent_bg=T.BG_BASE).pack(fill="x")

        self.content = tk.Frame(self.main, bg=T.BG_BASE)
        self.content.pack(fill="both", expand=True, padx=T.PAD, pady=(20, 16))

        self._pages: dict[str, tk.Frame] = {}
        for key, _, _ in PAGES:
            frame = tk.Frame(self.content, bg=T.BG_BASE)
            self._pages[key] = frame

        self._build_memory_page(self._pages["memory"])
        self._build_review_page(self._pages["review"])
        self._build_persona_page(self._pages["persona"])
        self._build_settings_page(self._pages["settings"])
        self._build_plugins_page(self._pages["plugins"])

    # ---- 记忆库 ----
    def _build_memory_page(self, parent: tk.Frame) -> None:
        composer = Card(parent, height=152, bg=T.BG_CARD, parent_bg=T.BG_BASE)
        composer.pack(fill="x")

        self._entry = tk.Text(composer, height=3, bg=T.BG_INPUT, fg=T.INK, relief="flat",
                              insertbackground=T.CYAN, font=T.F(14, family="serif"),
                              highlightthickness=1, highlightbackground=T.LINE_HAIR,
                              highlightcolor=T.CYAN, bd=0, wrap="word",
                              padx=12, pady=8)
        self._entry.place(x=20, y=16, relwidth=1.0, width=-40, height=70)
        self._entry.insert("1.0", "现在在想什么…")
        self._entry.configure(fg=T.INK_3)
        self._placeholder_on = True

        def _focus_in(_e: object) -> None:
            if self._placeholder_on:
                self._entry.delete("1.0", "end")
                self._entry.configure(fg=T.INK)
                self._placeholder_on = False

        def _focus_out(_e: object) -> None:
            if not self._entry.get("1.0", "end").strip():
                self._entry.insert("1.0", "现在在想什么…")
                self._entry.configure(fg=T.INK_3)
                self._placeholder_on = True

        self._entry.bind("<FocusIn>", _focus_in)
        self._entry.bind("<FocusOut>", _focus_out)
        self._entry.bind("<Control-Return>", lambda e: (self._add_entry(), "break")[1])

        self._kind_var = tk.StringVar(value="event")
        kind_box = tk.OptionMenu(composer, self._kind_var, *KINDS)
        kind_box.configure(bg=T.BG_CARD, fg=T.INK_2, activebackground=T.GLOW,
                           activeforeground=T.CYAN, relief="flat", bd=0,
                           highlightthickness=0, font=T.F(12))
        kind_box["menu"].configure(bg=T.BG_CARD, fg=T.INK_2, activebackground=T.GLOW,
                                   activeforeground=T.CYAN, font=T.F(12), bd=0)
        kind_box.place(x=18, y=100, width=96, height=34)

        FlatButton(composer, "记下来", self._add_entry, kind="primary",
                   width=104, height=34, parent_bg=T.BG_CARD).place(relx=1.0, x=-18, y=100, anchor="ne")

        head = tk.Frame(parent, bg=T.BG_BASE)
        head.pack(fill="x", pady=(18, 8))
        self._day_label = tk.Label(head, text=date.today().isoformat(), bg=T.BG_BASE,
                                   fg=T.INK, font=T.F(15, "bold"))
        self._day_label.pack(side="left")
        self._count_label = tk.Label(head, text="", bg=T.BG_BASE, fg=T.INK_3, font=T.F(12))
        self._count_label.pack(side="right")

        self._list = MemoryList(parent, self._on_row_selected)
        self._list.pack(fill="both", expand=True)

        foot = tk.Frame(parent, bg=T.BG_BASE)
        foot.pack(fill="x", pady=(8, 0))
        FlatButton(foot, "删除选中", self._delete_selected, kind="ghost",
                   width=100, height=30, parent_bg=T.BG_BASE).pack(side="left")

    # ---------------- 右栏 ----------------
    def _build_panel(self) -> None:
        self._panel_body = tk.Frame(self.panel, bg=T.BG_PANEL)
        self._panel_body.pack(fill="both", expand=True, padx=24, pady=24)
        self._render_panel()

    def _render_panel(self) -> None:
        for w in self._panel_body.winfo_children():
            w.destroy()
        stats = self.store.stats()
        tk.Label(self._panel_body, text="今日概览", bg=T.BG_PANEL, fg=T.INK,
                 font=T.F(13, "bold")).pack(anchor="w")
        today = len(self.store.entries_for_day(date.today().isoformat()))
        StatRow(self._panel_body, "记录", str(today)).pack(fill="x", pady=(12, 6))
        StatRow(self._panel_body, "连续", f"{stats['days']} 天").pack(fill="x", pady=(0, 12))
        HairLine(self._panel_body, parent_bg=T.BG_PANEL).pack(fill="x", pady=(0, 14))

        tk.Label(self._panel_body, text="类型", bg=T.BG_PANEL, fg=T.INK,
                 font=T.F(13, "bold")).pack(anchor="w", pady=(0, 10))
        chips = tk.Frame(self._panel_body, bg=T.BG_PANEL)
        chips.pack(fill="x")
        for i, k in enumerate(KINDS):
            Chip(chips, T.KIND_LABEL[k], active=(i == 0), dot=T.KIND_COLORS[k],
                 parent_bg=T.BG_PANEL).grid(row=i // 2, column=i % 2, padx=(0, 8), pady=(0, 8))

        HairLine(self._panel_body, parent_bg=T.BG_PANEL).pack(fill="x", pady=(14, 14))
        tk.Label(self._panel_body, text="语言", bg=T.BG_PANEL, fg=T.INK,
                 font=T.F(13, "bold")).pack(anchor="w", pady=(0, 8))
        box = tk.OptionMenu(self._panel_body, tk.StringVar(value="中文"), "中文", "English", "日本語", "한국어")
        box.configure(bg=T.BG_CARD, fg=T.INK_2, activebackground=T.GLOW, activeforeground=T.CYAN,
                      relief="flat", bd=0, highlightthickness=0, font=T.F(12))
        box["menu"].configure(bg=T.BG_CARD, fg=T.INK_2, activebackground=T.GLOW,
                              activeforeground=T.CYAN, bd=0, font=T.F(12))
        box.pack(fill="x")

    # ---- 复盘 ----
    def _build_review_page(self, parent: tk.Frame) -> None:
        bar = tk.Frame(parent, bg=T.BG_BASE)
        bar.pack(fill="x", pady=(0, 12))
        tk.Label(bar, text="日期", bg=T.BG_BASE, fg=T.INK_2, font=T.F(12)).pack(side="left")
        self._review_date = tk.StringVar(value=date.today().isoformat())
        entry = tk.Entry(bar, textvariable=self._review_date, bg=T.BG_CARD, fg=T.INK,
                         relief="flat", insertbackground=T.CYAN, font=T.F(13, family="mono"),
                         highlightthickness=1, highlightbackground=T.LINE_HAIR,
                         highlightcolor=T.CYAN, width=12)
        entry.pack(side="left", padx=(10, 16), ipady=4)

        self._offline = tk.BooleanVar(value=False)
        chk = tk.Checkbutton(bar, text="不连模型", variable=self._offline, bg=T.BG_BASE,
                             fg=T.INK_2, selectcolor=T.BG_CARD, activebackground=T.BG_BASE,
                             activeforeground=T.CYAN, font=T.F(12), bd=0, highlightthickness=0)
        chk.pack(side="left")
        FlatButton(bar, "生成复盘", self._run_review, kind="primary", width=100, height=32,
                   parent_bg=T.BG_BASE).pack(side="right")

        self._review_text = self._make_reader(parent)

    # ---- 人格 ----
    def _build_persona_page(self, parent: tk.Frame) -> None:
        bar = tk.Frame(parent, bg=T.BG_BASE)
        bar.pack(fill="x", pady=(0, 12))
        FlatButton(bar, "从最近复盘学习", self._run_distill, kind="primary", width=132,
                   height=32, parent_bg=T.BG_BASE).pack(side="left")
        FlatButton(bar, "刷新", self._refresh_persona, kind="ghost", width=72, height=32,
                   parent_bg=T.BG_BASE).pack(side="left", padx=10)
        self._persona_text = self._make_reader(parent)

    # ---- 设置 ----
    def _build_settings_page(self, parent: tk.Frame) -> None:
        card = Card(parent, height=420, parent_bg=T.BG_BASE)
        card.pack(fill="x")
        self._set_vars: dict[str, tk.StringVar] = {
            "base_url": tk.StringVar(value=self.cfg.model.base_url),
            "name": tk.StringVar(value=self.cfg.model.name),
            "api_key": tk.StringVar(value=self.cfg.model.api_key),
            "temperature": tk.StringVar(value=str(self.cfg.model.temperature)),
            "max_tokens": tk.StringVar(value=str(self.cfg.model.max_tokens)),
            "timeout": tk.StringVar(value=str(self.cfg.model.timeout)),
        }
        rows = [("接口地址", "base_url"), ("模型名", "name"), ("API Key", "api_key"),
                ("temperature", "temperature"), ("max_tokens", "max_tokens"), ("超时(秒)", "timeout")]
        for i, (label, key) in enumerate(rows):
            y = 26 + i * 52
            tk.Label(card, text=label, bg=T.BG_CARD, fg=T.INK_2,
                     font=T.F(12)).place(x=24, y=y + 6)
            e = tk.Entry(card, textvariable=self._set_vars[key], bg=T.BG_INPUT, fg=T.INK,
                         relief="flat", insertbackground=T.CYAN, font=T.F(13),
                         highlightthickness=1, highlightbackground=T.LINE_HAIR,
                         highlightcolor=T.CYAN)
            e.place(x=140, y=y, width=420, height=32)

        self._settings_hint = tk.Label(card, text="", bg=T.BG_CARD, fg=T.INK_3, font=T.F(12))
        self._settings_hint.place(x=24, y=348)
        FlatButton(card, "保存配置", self._save_settings, kind="primary", width=104, height=34,
                   parent_bg=T.BG_CARD).place(x=20, y=378)
        FlatButton(card, "测试连接", self._test_model, kind="ghost", width=104, height=34,
                   parent_bg=T.BG_CARD).place(x=136, y=378)

        info = tk.Label(parent, text=f"数据目录：{self.cfg.home}", bg=T.BG_BASE, fg=T.INK_3,
                        font=T.F(12))
        info.pack(anchor="w", pady=(16, 0))

    # ---- 插件 ----
    def _build_plugins_page(self, parent: tk.Frame) -> None:
        self._plugins_box = tk.Frame(parent, bg=T.BG_BASE)
        self._plugins_box.pack(fill="both", expand=True)
        self._refresh_plugins()

    def _refresh_plugins(self) -> None:
        for w in self._plugins_box.winfo_children():
            w.destroy()
        from ..plugins import PluginContext, PluginManager

        ctx = PluginContext(config=self.cfg, store=self.store, i18n=self.i18n, logger=lambda m: None)
        pm = PluginManager(ctx)
        pm.load_all()
        rows = pm.describe()
        if not rows:
            tk.Label(self._plugins_box, text="还没有插件。把 .py 放进 " + str(self.cfg.plugin_dir),
                     bg=T.BG_BASE, fg=T.INK_3, font=T.F(13)).pack(anchor="w")
            return
        for r in rows:
            card = Card(self._plugins_box, height=72, parent_bg=T.BG_BASE)
            card.pack(fill="x", pady=(0, 10))
            ok = r["status"] == "ok"
            card.create_oval(26, 30, 34, 38, fill=T.CYAN if ok else T.ERROR, outline="")
            card.create_text(46, 28, text=r["name"], anchor="w", fill=T.INK, font=T.F(14, "bold"))
            card.create_text(46, 48, text=f"v{r['version']}  ·  " + (", ".join(r["hooks"]) or "无钩子"),
                             anchor="w", fill=T.INK_3, font=T.F(11, family="mono"))
            if not ok:
                card.create_text(640, 36, text=r["description"][:60], anchor="w",
                                 fill=T.ERROR, font=T.F(11))

    # ---------------- 通用 ----------------
    def _make_reader(self, parent: tk.Frame) -> tk.Text:
        wrap = tk.Frame(parent, bg=T.BG_CARD, highlightthickness=1,
                        highlightbackground=T.LINE_HAIR)
        wrap.pack(fill="both", expand=True)
        text = tk.Text(wrap, bg=T.BG_CARD, fg=T.INK, relief="flat", wrap="word",
                       insertbackground=T.CYAN, font=T.F(15, family="serif"),
                       padx=24, pady=20, spacing1=4, spacing3=8,
                       highlightthickness=0, bd=0, state="disabled", selectbackground=T.SOFT)
        sb = tk.Scrollbar(wrap, command=text.yview, bg=T.BG_PANEL, troughcolor=T.BG_BASE,
                          relief="flat", bd=0, width=10, activebackground=T.SOFT)
        text.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        text.pack(side="left", fill="both", expand=True)
        return text

    def _write(self, widget: tk.Text, content: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", content)
        widget.configure(state="disabled")

    # ---------------- 页面切换 ----------------
    def _show_page(self, key: str, search: str | None = None) -> None:
        self._page = key
        for k, frame in self._pages.items():
            if k == key:
                frame.pack(fill="both", expand=True)
            else:
                frame.pack_forget()
        self._title.configure(text=dict((k, l) for k, l, _ in PAGES)[key])
        for k, item in self._navs.items():
            item.set_active(k == key)

        if key == "memory":
            self._refresh_today(search)
        elif key == "persona":
            self._refresh_persona()
        self._render_panel()

    # ---------------- 动作 ----------------
    def _add_entry(self) -> None:
        if getattr(self, "_placeholder_on", False):
            return
        text = self._entry.get("1.0", "end").strip()
        if not text:
            return
        self.store.add_entry(text=text, kind=self._kind_var.get(), source="desktop")
        self._entry.delete("1.0", "end")
        self._entry.insert("1.0", "现在在想什么…")
        self._entry.configure(fg=T.INK_3)
        self._placeholder_on = True
        self._refresh_today()

    def _refresh_today(self, search: str | None = None) -> None:
        q = (search or "").strip()
        entries = self.store.search(q, limit=200) if q else self.store.entries_for_day(date.today().isoformat())
        if not search:
            entries = list(reversed(entries))
        self._list.set_entries(entries)
        self._count_label.configure(
            text=(f"搜索「{q}」· {len(entries)} 条" if q else f"今天 {len(entries)} 条")
        )
        self._render_panel()

    def _on_row_selected(self, idx: int | None) -> None:
        pass

    def _do_search(self) -> None:
        if getattr(self, "_search_on", True):
            return
        q = self._search.get().strip()
        if q:
            self._refresh_today(q)

    def _delete_selected(self) -> None:
        entry = self._list.selected_entry()
        if entry is None:
            return
        self.store.delete_entry(entry.id)
        self._refresh_today()

    def _run_review(self) -> None:
        day = self._review_date.get().strip() or date.today().isoformat()
        offline = self._offline.get()

        def work() -> Any:
            return generate_review(self.store, self.cfg, self.i18n, day=day, offline=offline)

        def done(review: Any) -> None:
            if review is None:
                self._write(self._review_text, f"{day} 没有记录，跳过。")
                return
            body = render_review(review, self.i18n)
            if review.isolated:
                body += f"\n提示：{review.isolated} 条记录疑似含指令性文本，已隔离。\n"
            if review.dropped:
                body += "\n提示：本次复盘疑似被指令带偏，已丢弃。\n"
            self._write(self._review_text, body)
            self._refresh_today()

        self._run_bg("生成复盘", work, done)

    def _run_distill(self) -> None:
        def work() -> Any:
            return distill(self.store, self.cfg, self.i18n, days=7)

        def done(learned: Any) -> None:
            self._write(self._persona_text,
                        f"本次学到 {len(learned)} 条观察。\n\n" + render_profile(self.store, self.i18n))

        self._run_bg("学习中", work, done)

    def _refresh_persona(self) -> None:
        if hasattr(self, "_persona_text"):
            self._write(self._persona_text, render_profile(self.store, self.i18n))

    def _save_settings(self) -> None:
        try:
            self.cfg.model.base_url = self._set_vars["base_url"].get().strip()
            self.cfg.model.name = self._set_vars["name"].get().strip()
            self.cfg.model.api_key = self._set_vars["api_key"].get().strip()
            self.cfg.model.temperature = float(self._set_vars["temperature"].get())
            self.cfg.model.max_tokens = int(self._set_vars["max_tokens"].get())
            self.cfg.model.timeout = int(self._set_vars["timeout"].get())
            self.cfg.save()
            self._settings_hint.configure(text=f"已保存到 {self.cfg.config_path}", fg=T.CYAN)
        except ValueError as exc:
            self._settings_hint.configure(text=f"配置不合法：{exc}", fg=T.ERROR)

    def _test_model(self) -> None:
        from ..llm import LLMClient

        self._save_settings()
        client = LLMClient(self.cfg.model)

        def work() -> Any:
            return client.health()

        def done(result: Any) -> None:
            ok, detail = result
            self._settings_hint.configure(text=("可用：" if ok else "不可用：") + str(detail)[:90],
                                          fg=T.CYAN if ok else T.ERROR)

        self._run_bg("测试连接", work, done)

    # ---------------- 后台任务 ----------------
    def _run_bg(self, label: str, fn: Callable[[], Any], done: Callable[[Any], None]) -> None:
        if self._busy:
            return
        self._busy = True
        self._set_status(f"{label}…")

        def worker() -> None:
            try:
                self._work.put(("ok", (done, fn())))
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
                    self._set_status("模型已连接")
                    done(result)
                else:
                    self._set_status("模型已连接")
                    self._write(
                        self._review_text if hasattr(self, "_review_text") else self._persona_text,
                        f"出错了：{payload}",
                    )
        except queue.Empty:
            pass
        self.after(120, self._drain_queue)

    def _set_status(self, text: str) -> None:
        if hasattr(self, "_status"):
            color = T.CYAN if "连接" in text else T.INK_3
            self._status.configure(text=text, fg=T.INK_2)
            self._dot.delete("all")
            self._dot.create_oval(1, 1, 9, 9, fill=color, outline="")

    def _on_close(self) -> None:
        try:
            self.store.close()
        finally:
            self.destroy()


def main(argv: list[str] | None = None) -> int:
    cfg = Config.load()
    cfg.ensure_dirs()
    MemoirApp(cfg).mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
