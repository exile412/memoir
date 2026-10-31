"""本地 Web 服务：一套代码，电脑和手机浏览器都能用。

零第三方依赖——标准库 http.server 手写路由，起服务只要一行：

    memoir web

默认监听 0.0.0.0:8765，手机连同一 WiFi 访问 http://<电脑IP>:8765 即可。
"""

from __future__ import annotations

import json
import mimetypes
import re
import socket
import threading
import webbrowser
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from .. import __version__
from ..config import Config
from ..i18n import I18N
from ..llm import LLMClient, LLMError
from ..persona import distill, render_profile
from ..review import generate_review, render_review
from ..storage import Store

STATIC_DIR = Path(__file__).parent / "static"

CODE_HINT = re.compile(
    r"(^|\n)\s*(def |class |function |const |let |import |from |#include|public |private |"
    r"SELECT |CREATE TABLE|package |fn )"
)
WALLPAPER_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


def _lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:  # noqa: BLE001
        return "127.0.0.1"


def _detect_wallpaper_dir(cfg: Config) -> Path | None:
    custom = cfg.extra.get("wallpaper_dir")
    if custom and Path(custom).is_dir():
        return Path(custom)
    for g in (
        Path("C:/Program Files (x86)/Steam/steamapps/workshop/content/431960"),
        Path("D:/Steam/steamapps/workshop/content/431960"),
        Path("E:/Steam/steamapps/workshop/content/431960"),
    ):
        if g.is_dir():
            return g
    return None


class App:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.i18n = I18N(cfg.lang)
        self.store = Store(cfg.db_path)

    def close(self) -> None:
        self.store.close()

    def llm(self, system: str, user: str, max_tokens: int = 800) -> str:
        res = LLMClient(self.cfg.model).chat(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            max_tokens=max_tokens,
        )
        return (res.text or "").strip()

    def polish(self, text: str) -> str:
        system = (
            "你是一个文字编辑。把用户的口语记录改写得通顺、有质感，但必须严格保留原意、"
            "事实和情绪倾向，不得添加原文没有的信息，不得拔高或美化事实。"
            "长度控制在原文的 0.8 到 1.3 倍。只输出改写后的正文，不要解释。"
        )
        try:
            return self.llm(system, text, max_tokens=700) or text
        except LLMError:
            return text

    def make_title(self, text: str) -> str:
        system = "给下面这段记录起一个标题，8 个字以内，不要标点不要引号，只输出标题本身。"
        try:
            t = self.llm(system, text[:800], max_tokens=32)
            t = re.sub(r"[\s\"'“”「」《》]", "", (t or "").splitlines()[0] if t else "")
            return t[:12] or text.strip()[:12]
        except LLMError:
            return text.strip()[:12]

    def summarize(self, text: str) -> str:
        system = (
            "把用户的记录整理成一段清晰的笔记：保留全部事实与关键细节，按逻辑组织，"
            "去掉重复和口头语。不要评价，不要添加原文没有的内容。只输出整理后的正文。"
        )
        try:
            return self.llm(system, text, max_tokens=700) or text
        except LLMError:
            return text


def list_wallpapers(app: App) -> list[dict[str, str]]:
    root = _detect_wallpaper_dir(app.cfg)
    if not root:
        return []
    out: list[dict[str, str]] = []
    try:
        for proj in root.iterdir():
            if not proj.is_dir():
                continue
            for f in proj.iterdir():
                if f.suffix.lower() in WALLPAPER_EXT and f.is_file():
                    out.append({"id": f"{proj.name}/{f.name}", "name": proj.name})
                    break
            if len(out) >= 80:
                break
    except OSError:
        return out
    return out


def wallpaper_path(app: App, wid: str) -> Path | None:
    root = _detect_wallpaper_dir(app.cfg)
    if not root:
        return None
    target = (root / unquote(wid)).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError:
        return None
    return target if target.is_file() else None


def build_bootstrap(app: App) -> dict[str, Any]:
    today = date.today().isoformat()
    entries = app.store.entries_for_day(today)
    return {
        "version": __version__,
        "greeting": "今天想要记录什么？",
        "today": today,
        "todayCount": len(entries),
        "stats": app.store.stats(),
        "lang": app.cfg.lang,
        "model": {"name": app.cfg.model.name, "baseUrl": app.cfg.model.base_url},
        "wallpapers": list_wallpapers(app),
        "groups": app.store.list_groups(),
    }


def run(cfg: Config | None = None, host: str = "0.0.0.0", port: int = 8765,
        open_browser: bool = True) -> None:
    cfg = cfg or Config.load()
    cfg.ensure_dirs()

    load_lock = threading.Lock()
    app = App(cfg)
    lan = _lan_ip()

    def handle(method: str, path: str, query: dict[str, list[str]], body: bytes) -> tuple[int, str, bytes]:
        with load_lock:
            return _route(app, method, path, query, body)

    class Handler(BaseHTTPRequestHandler):
        server_version = f"memoir/{__version__}"

        def log_message(self, fmt: str, *args: Any) -> None:  # 静默访问日志
            return

        def _send(self, status: int, ctype: str, payload: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            try:
                self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def _json(self, status: int, obj: Any) -> None:
            data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self._send(status, "application/json; charset=utf-8", data)

        def do_GET(self) -> None:  # noqa: N802
            try:
                url = urlparse(self.path)
                status, ctype, payload = handle("GET", url.path, parse_qs(url.query), b"")
                self._send(status, ctype, payload)
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"error": f"{type(exc).__name__}: {exc}"})

        def do_POST(self) -> None:  # noqa: N802
            try:
                url = urlparse(self.path)
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b""
                status, ctype, payload = handle("POST", url.path, parse_qs(url.query), body)
                self._send(status, ctype, payload)
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"error": f"{type(exc).__name__}: {exc}"})

        def do_DELETE(self) -> None:  # noqa: N802
            try:
                url = urlparse(self.path)
                status, ctype, payload = handle("DELETE", url.path, parse_qs(url.query), b"")
                self._send(status, ctype, payload)
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"error": f"{type(exc).__name__}: {exc}"})

    httpd = ThreadingHTTPServer((host, port), Handler)
    url = f"http://127.0.0.1:{port}"
    print(f"memoir web  v{__version__}")
    print(f"  本机   {url}")
    print(f"  手机   http://{lan}:{port}   （需同一 WiFi）")
    print("  数据   " + str(cfg.home))
    print("  Ctrl+C 停止")
    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    finally:
        httpd.server_close()
        app.close()


def _route(app: App, method: str, path: str, query: dict[str, list[str]], body: bytes) -> tuple[int, str, bytes]:
    """把手写路由放这里，保持 Handler 干净。"""
    from .routes import dispatch

    return dispatch(app, method, path, query, body, STATIC_DIR)
