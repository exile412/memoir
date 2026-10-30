"""桌面入口。

真正的界面实现在 memoir/ui/app.py（深色主题、自绘控件）。
这里只做转发，保持 `memoir gui` 与 `memoir-desktop` 入口不变。
"""

from .ui.app import MemoirApp, main

__all__ = ["MemoirApp", "main"]

if __name__ == "__main__":
    raise SystemExit(main())
