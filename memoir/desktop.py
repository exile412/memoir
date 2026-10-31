"""桌面入口：原生窗口 + 网页界面。

双击 exe 得到的是一个真正的桌面窗口，但里面跑的是 Web 版界面——
这样壁纸、美化、语法高亮、登录这些只在网页端有的能力，桌面端也能用上。

旧的纯 tkinter 界面还留着，用 memoir gui 打开。
"""

from __future__ import annotations

import socket
import threading
import time
import webbrowser

from .config import Config


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def _wait_port(port: int, timeout: float = 10.0) -> bool:
    start = time.time()
    while time.time() - start < timeout:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.35):
                return True
        except OSError:
            time.sleep(0.15)
    return False


def _pick_port(preferred: int = 8765) -> int:
    if _port_free(preferred):
        return preferred
    for candidate in range(preferred + 1, preferred + 20):
        if _port_free(candidate):
            return candidate
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def main(argv=None) -> int:
    cfg = Config.load()
    cfg.ensure_dirs()
    port = _pick_port()
    url = f"http://127.0.0.1:{port}"

    from .web.app import run as run_web

    threading.Thread(
        target=run_web,
        kwargs={"cfg": cfg, "port": port, "open_browser": False},
        daemon=True,
    ).start()

    if not _wait_port(port):
        webbrowser.open(url)
        print("Web 服务没能启动，已改用系统浏览器")
        time.sleep(3)
        return 1

    try:
        import webview
    except Exception:
        webbrowser.open(url)
        print(f"没有可用的内嵌浏览器，已用系统浏览器打开：{url}")
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            return 0

    webview.create_window(
        "memoir · 记忆",
        url,
        width=1280,
        height=820,
        min_size=(900, 620),
        background_color="#131313",
    )
    webview.start()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
