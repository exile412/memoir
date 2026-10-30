"""自绘控件。tkinter 原生控件全是直角，这里用 Canvas 补齐圆角、描边与微光。

原则：所有视觉都由 theme.py 的颜色驱动，控件本身不藏魔法数字。
"""

from __future__ import annotations

import tkinter as tk
from typing import Callable

from . import theme as T


def round_rect(canvas: tk.Canvas, x1: float, y1: float, x2: float, y2: float,
               r: float = T.CARD_R, **kw) -> int:
    """用平滑多边形画圆角矩形。tkinter 没有原生圆角。"""
    r = min(r, (x2 - x1) / 2, (y2 - y1) / 2)
    pts = [
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
        x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
        x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
    ]
    return canvas.create_polygon(pts, smooth=True, **kw)


class Card(tk.Canvas):
    """一块圆角卡片。内容自己往上面画。"""

    def __init__(self, master: tk.Misc, height: int = 64, radius: int = T.CARD_R,
                 bg: str = T.BG_CARD, border: str = T.LINE_HAIR, parent_bg: str = T.BG_BASE, **kw):
        super().__init__(master, height=height, bg=parent_bg, highlightthickness=0, bd=0, **kw)
        self._radius = radius
        self._fill = bg
        self._border = border
        self.bind("<Configure>", self._redraw)

    def set_colors(self, fill: str, border: str) -> None:
        self._fill, self._border = fill, border
        self._redraw()

    def _redraw(self, _event: object = None) -> None:
        self.delete("bg")
        w = self.winfo_width() or 100
        h = self.winfo_height() or 64
        if w <= 2 or h <= 2:
            return
        round_rect(self, 1, 1, w - 1, h - 1, self._radius,
                   fill=self._fill, outline=self._border, width=1, tags="bg")
        self.tag_lower("bg")


class FlatButton(tk.Canvas):
    """圆角按钮。kind: primary(实心青) / ghost(描边)。"""

    def __init__(self, master: tk.Misc, text: str, command: Callable[[], None],
                 kind: str = "primary", width: int = 96, height: int = 32,
                 parent_bg: str = T.BG_CARD, **kw):
        super().__init__(master, width=width, height=height, bg=parent_bg,
                         highlightthickness=0, bd=0, cursor="hand2", **kw)
        self._label = text
        self._command = command
        self._kind = kind
        # 注意：不能叫 _w / _h —— 那是 tkinter Widget 的内部属性
        self._bw, self._bh = width, height
        self.bind("<Button-1>", lambda e: self._command())
        self.bind("<Enter>", lambda e: self._paint(hover=True))
        self.bind("<Leave>", lambda e: self._paint(hover=False))
        self._paint()

    def _paint(self, hover: bool = False) -> None:
        self.delete("all")
        if self._kind == "primary":
            fill = T.SOFT if hover else T.CYAN
            ink = "#08111A"
            outline = ""
        else:
            fill = T.GLOW if hover else ""
            ink = T.CYAN if hover else T.INK_2
            outline = T.SOFT if hover else T.LINE_STRONG
        round_rect(self, 1, 1, self._bw - 1, self._bh - 1, T.BTN_R,
                   fill=fill or T.BG_CARD, outline=outline, width=1)
        self.create_text(self._bw / 2, self._bh / 2 + 1, text=self._label,
                         fill=ink, font=T.F(12, "bold"))


class NavItem(tk.Canvas):
    """侧栏导航项：图标 + 文字，选中时左侧 2px 竖条 + 背后微光。"""

    def __init__(self, master: tk.Misc, label: str, icon: str,
                 command: Callable[[], None], active: bool = False):
        super().__init__(master, height=52, bg=T.BG_SIDE, highlightthickness=0,
                         bd=0, cursor="hand2")
        self._label = label
        self._icon = icon
        self._command = command
        self._active = active
        self._hover = False
        self.bind("<Button-1>", lambda e: self._command())
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Configure>", lambda e: self._paint())

    def set_active(self, active: bool) -> None:
        self._active = active
        self._paint()

    def _on_enter(self, _e: object) -> None:
        self._hover = True
        self._paint()

    def _on_leave(self, _e: object) -> None:
        self._hover = False
        self._paint()

    def _paint(self) -> None:
        self.delete("all")
        h = self.winfo_height() or 52
        w = self.winfo_width() or T.SIDEBAR_W
        color = T.CYAN if self._active else (T.INK_2 if self._hover else T.INK_3)
        if self._active:
            self.create_rectangle(0, 0, w, h, fill=T.GLOW, outline="")
            self.create_rectangle(0, 10, 2, h - 10, fill=T.CYAN, outline="")
        elif self._hover:
            self.create_rectangle(0, 7, w, h - 7, fill=T.BG_CARD, outline="")
        self._draw_icon(30, h / 2, color)
        self.create_text(52, h / 2 + 1, text=self._label, anchor="w",
                         fill=T.INK if self._active else color,
                         font=T.F(13, "bold" if self._active else "normal"))

    def _draw_icon(self, cx: float, cy: float, color: str) -> None:
        o = dict(fill="", outline=color, width=1.2)
        if self._icon == "lib":
            self.create_rectangle(cx - 6, cy - 6, cx + 6, cy + 6, **o)
            self.create_line(cx - 6, cy - 2, cx + 6, cy - 2, fill=color, width=1.2)
        elif self._icon == "review":
            self.create_rectangle(cx - 6, cy - 6, cx + 6, cy + 6, **o)
            self.create_line(cx - 4, cy - 2, cx + 4, cy - 2, fill=color, width=1.2)
            self.create_line(cx - 4, cy + 2, cx + 2, cy + 2, fill=color, width=1.2)
        elif self._icon == "person":
            self.create_oval(cx - 3, cy - 6, cx + 3, cy, **o)
            self.create_arc(cx - 6, cy, cx + 6, cy + 12, start=0, extent=180, style="arc",
                            outline=color, width=1.2)
        elif self._icon == "gear":
            self.create_oval(cx - 3.2, cy - 3.2, cx + 3.2, cy + 3.2, **o)
            self.create_oval(cx - 7, cy - 7, cx + 7, cy + 7, outline=color, width=1.2,
                             dash=(2, 3))
        else:
            self.create_rectangle(cx - 6, cy - 6, cx + 6, cy + 6, **o)
            self.create_oval(cx - 1.6, cy - 1.6, cx + 1.6, cy + 1.6, fill=color, outline="")


class Chip(tk.Canvas):
    """筛选胶囊。"""

    def __init__(self, master: tk.Misc, text: str, active: bool = False,
                 dot: str = "", command: Callable[[], None] | None = None,
                 parent_bg: str = T.BG_PANEL, width: int = 78):
        super().__init__(master, width=width, height=28, bg=parent_bg,
                         highlightthickness=0, bd=0, cursor="hand2")
        self._text = text
        self._active = active
        self._dot = dot
        self._command = command
        self._chip_w = width
        self.bind("<Button-1>", lambda e: self._command() if self._command else None)
        self.bind("<Configure>", lambda e: self._paint())

    def set_active(self, active: bool) -> None:
        self._active = active
        self._paint()

    def _paint(self) -> None:
        self.delete("all")
        if self._active:
            round_rect(self, 1, 1, self._chip_w - 1, 27, 14, fill=T.GLOW, outline=T.SOFT, width=1)
        else:
            round_rect(self, 1, 1, self._chip_w - 1, 27, 14, fill=T.BG_PANEL,
                       outline=T.LINE_HAIR, width=1)
        ink = T.CYAN if self._active else T.INK_2
        tx = 14
        if self._dot:
            self.create_oval(tx - 3, 11, tx + 3, 17, fill=self._dot, outline="")
            tx += 12
        self.create_text(tx, 15, text=self._text, anchor="w", fill=ink, font=T.F(12))


class HairLine(tk.Canvas):
    def __init__(self, master: tk.Misc, parent_bg: str = T.BG_PANEL, color: str = T.LINE_HAIR):
        super().__init__(master, height=1, bg=parent_bg, highlightthickness=0, bd=0)
        self._color = color
        self.bind("<Configure>", self._paint)

    def _paint(self, _e: object = None) -> None:
        self.delete("all")
        self.create_line(0, 0, self.winfo_width(), 0, fill=self._color)


class ScalePattern(tk.Canvas):
    """鱼鳞电路纹。只做描边，透明度用暗色近似（tk 无 alpha）。"""

    def __init__(self, master: tk.Misc, cols: int = 6, rows: int = 4,
                 parent_bg: str = T.BG_SIDE, color: str = "#152232"):
        w = cols * 30 + 20
        h = rows * 26 + 20
        super().__init__(master, width=w, height=h, bg=parent_bg,
                         highlightthickness=0, bd=0)
        self._cols, self._rows, self._color = cols, rows, color
        self._paint()

    def _paint(self) -> None:
        self.delete("all")
        r, dx, dy = 22, 30, 26
        for j in range(self._rows):
            for i in range(self._cols):
                cx = 10 + i * dx + (dx // 2 if j % 2 else 0)
                cy = 20 + j * dy
                self.create_arc(cx - r, cy - r, cx + r, cy + r, start=0, extent=180,
                                style="arc", outline=self._color, width=1)
                self.create_oval(cx - r - 1.4, cy - 1.4, cx - r + 1.4, cy + 1.4,
                                 fill=self._color, outline="")


class StatRow(tk.Frame):
    """右栏的一行统计：左标签右数值。"""

    def __init__(self, master: tk.Misc, label: str, value: str):
        super().__init__(master, bg=T.BG_PANEL)
        tk.Label(self, text=label, bg=T.BG_PANEL, fg=T.INK_2, font=T.F(12)).pack(side="left")
        self._value = tk.Label(self, text=value, bg=T.BG_PANEL, fg=T.INK, font=T.F(13, "bold"))
        self._value.pack(side="right")

    def set(self, value: str) -> None:
        self._value.configure(text=value)
