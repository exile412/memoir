"""视觉主题：色板、字体、尺寸。

所有值来自 docs/05-ui-design.md，改这里就等于换皮肤。
字号一律用负数（像素），避免 Windows 高 DPI 下被二次缩放。
"""

from __future__ import annotations

import sys

# ---------- 色板 ----------
BG_BASE = "#0A1018"      # 窗口底
BG_SIDE = "#0D1520"      # 左侧导航
BG_PANEL = "#111A28"     # 右侧参数栏
BG_CARD = "#141F30"      # 卡片、记录行
BG_CARD_HOVER = "#182638"
BG_INPUT = "#0E1622"

LINE_HAIR = "#1C2A3D"    # 1px 分隔、描边
LINE_STRONG = "#26374F"  # 输入框描边

INK = "#E3EBF5"          # 主文字
INK_2 = "#93A6BF"        # 次要
INK_3 = "#5E7089"        # 三级 / 占位

CYAN = "#6FD3D8"         # 唯一强调色
SOFT = "#3E8FA0"
GLOW = "#16283A"         # 微光的近似色（tk 无 alpha，用实色替代）

WARN = "#C9A36B"
ERROR = "#C97B7B"

KIND_COLORS = {
    "event": "#6FD3D8",
    "thought": "#9C8FC4",
    "feeling": "#C9A36B",
    "note": "#7B8CA6",
}

KIND_LABEL = {"event": "事件", "thought": "想法", "feeling": "情绪", "note": "备注"}

# ---------- 字体 ----------
_UI_SERIF = ("Source Han Serif SC", "Songti SC", "SimSun", "Georgia")
_UI_SANS = ("Microsoft YaHei UI", "PingFang SC", "Segoe UI")
_UI_MONO = ("JetBrains Mono", "Consolas", "Courier New")


def _pick(candidates: tuple[str, ...], fallback: str) -> str:
    """挑一个系统里存在的字体，挑不到就用回退。"""
    try:
        from tkinter import font as tkfont
        import tkinter as tk

        root = tk._default_root
        if root is None:
            return candidates[0]
        available = set(tkfont.families(root))
        for name in candidates:
            if name in available:
                return name
    except Exception:  # noqa: BLE001
        pass
    return fallback


_cache: dict[str, str] = {}


def sans() -> str:
    if "sans" not in _cache:
        _cache["sans"] = _pick(_UI_SANS, "Segoe UI")
    return _cache["sans"]


def serif() -> str:
    if "serif" not in _cache:
        _cache["serif"] = _pick(_UI_SERIF, "SimSun")
    return _cache["serif"]


def mono() -> str:
    if "mono" not in _cache:
        _cache["mono"] = _pick(_UI_MONO, "Consolas")
    return _cache["mono"]


def F(size: int, weight: str = "normal", family: str = "sans") -> tuple:
    """构造字体元组。size 单位是像素（负数）。"""
    fam = {"sans": sans, "serif": serif, "mono": mono}[family]()
    return (fam, -size, weight)


# ---------- 尺寸 ----------
SIDEBAR_W = 220
PANEL_W = 280
TOPBAR_H = 56
ROW_H = 76
CARD_R = 12
BTN_R = 8
PAD = 32
