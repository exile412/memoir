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

from ..users import USER_COOKIE, UserStore
from .auth import COOKIE_NAME, TOKEN_DAYS, Auth

STATIC_DIR = Path(__file__).parent / "static"

CODE_HINT = re.compile(
    r"(^|\n)\s*(def |class |function |const |let |import |from |#include|public |private |"
    r"SELECT |CREATE TABLE|package |fn )"
)
WALLPAPER_IMAGE = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
WALLPAPER_VIDEO = {".mp4", ".webm"}
VIDEO_CTYPE = {".mp4": "video/mp4", ".webm": "video/webm"}


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
        self.auth = Auth(cfg.home)
        secret = cfg.extra.get("user_secret") or ""
        if not secret:
            import secrets as _secrets

            secret = _secrets.token_hex(32)
            cfg.extra["user_secret"] = secret
            try:
                cfg.save()
            except OSError:
                pass
        self.users = UserStore(self.store, secret)
        self._local = threading.local()

    def _current_user(self) -> int | None:
        """当前请求的登录用户（由 Handler 每请求写入，线程隔离）。"""
        return getattr(self._local, "user_id", None)

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
    """列出壁纸。动态优先——有视频就用视频，没有才退回图片。"""
    root = _detect_wallpaper_dir(app.cfg)
    if not root:
        return []
    out: list[dict[str, str]] = []
    try:
        for proj in sorted(root.iterdir()):
            if not proj.is_dir():
                continue
            videos: list[Path] = []
            images: list[Path] = []
            for f in proj.iterdir():
                if not f.is_file():
                    continue
                ext = f.suffix.lower()
                if ext in WALLPAPER_VIDEO:
                    videos.append(f)
                elif ext in WALLPAPER_IMAGE:
                    images.append(f)
            pick: Path | None = None
            kind = ""
            if videos:
                # 优先非 preview 命名的视频
                videos.sort(key=lambda x: ("preview" in x.name.lower(), x.name))
                pick, kind = videos[0], "video"
            elif images:
                images.sort(key=lambda x: ("preview" in x.name.lower(), -x.stat().st_size))
                pick, kind = images[0], "image"
            if pick is None:
                continue
            out.append({
                "id": f"{proj.name}/{pick.name}",
                "name": proj.name,
                "kind": kind,
                "size": str(pick.stat().st_size),
            })
            if len(out) >= 120:
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
    auth = app.auth
    lan = _lan_ip()

    def handle(method: str, path: str, query: dict[str, list[str]], body: bytes) -> tuple[int, str, bytes]:
        with load_lock:
            return _route(app, method, path, query, body)

    class Handler(BaseHTTPRequestHandler):
        server_version = f"memoir/{__version__}"

        def log_message(self, fmt: str, *args: Any) -> None:  # 静默访问日志
            return

        # ---------- 认证 ----------
        def _cookie(self, name: str) -> str:
            raw = self.headers.get("Cookie") or ""
            for part in raw.split(";"):
                k, _, v = part.strip().partition("=")
                if k == name:
                    return v
            return ""

        def _user_id(self) -> int | None:
            token = self._cookie(USER_COOKIE)
            uid = app.users.check_token(token) if token else None
            # 每个请求把当前用户写进 store，查询自动按人隔离
            app.store.current_user_id = uid or 0
            return uid

        def _user_login(self, body: bytes, register: bool) -> None:
            try:
                data = json.loads(body.decode("utf-8") or "{}")
            except Exception:  # noqa: BLE001
                self._json(400, {"error": "请求体不合法"})
                return
            email = str(data.get("email") or "").strip()
            password = str(data.get("password") or "")
            try:
                user = (
                    app.users.register(email, password, str(data.get("nickname") or ""))
                    if register
                    else app.users.login(email, password)
                )
                if register:
                    # 注册时把未登录状态下的记录并入这个账号
                    app.store.claim_anonymous(int(user["id"]))
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
                return
            token = app.users.make_token(int(user["id"]))
            payload = json.dumps({"ok": True, "user": user}, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header(
                "Set-Cookie",
                f"{USER_COOKIE}={token}; Path=/; Max-Age={90 * 86400}; SameSite=Lax; HttpOnly",
            )
            self.end_headers()
            self.wfile.write(payload)

        def _user_logout(self) -> None:
            payload = json.dumps({"ok": True}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Set-Cookie", f"{USER_COOKIE}=; Path=/; Max-Age=0; SameSite=Lax")
            self.end_headers()
            self.wfile.write(payload)

        def _authorized(self, path: str) -> bool:
            if not auth.enabled:
                return True
            if path in ("/", "/index.html") or path.startswith("/static/"):
                return True
            if path.startswith("/api/auth/") or path.startswith("/api/user/"):
                return True
            return auth.valid(self._cookie(COOKIE_NAME))

        def _require_auth(self, path: str) -> bool:
            if self._authorized(path):
                return True
            self._json(401, {"error": "unauthorized", "needLogin": True})
            return False

        def _login(self, body: bytes) -> None:
            try:
                data = json.loads(body.decode("utf-8") or "{}")
            except Exception:  # noqa: BLE001
                self._json(400, {"error": "请求体不合法"})
                return
            if not auth.check(str(data.get("password") or "")):
                self._json(401, {"error": "密码不正确"})
                return
            token = auth.make_token()
            payload = json.dumps({"ok": True}, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header(
                "Set-Cookie",
                f"{COOKIE_NAME}={token}; Path=/; Max-Age={TOKEN_DAYS * 86400}; SameSite=Lax; HttpOnly",
            )
            self.end_headers()
            self.wfile.write(payload)

        def _logout(self) -> None:
            payload = json.dumps({"ok": True}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Set-Cookie", f"{COOKIE_NAME}=; Path=/; Max-Age=0; SameSite=Lax")
            self.end_headers()
            self.wfile.write(payload)

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
                app._local.user_id = self._user_id()
                if not self._require_auth(url.path):
                    return
                if url.path == "/api/wallpaper":
                    self._wallpaper(parse_qs(url.query))
                    return
                status, ctype, payload = handle("GET", url.path, parse_qs(url.query), b"")
                self._send(status, ctype, payload)
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"error": f"{type(exc).__name__}: {exc}"})

        def _wallpaper(self, query: dict[str, list[str]]) -> None:
            """壁纸文件。支持 Range，视频才能边下边播、拖进度条。"""
            import mimetypes as _mt

            from .app import wallpaper_path

            wid = query.get("id", [""])[0]
            path = wallpaper_path(app, wid)
            if not path:
                self._json(404, {"error": "not found"})
                return
            size = path.stat().st_size
            ctype = _mt.guess_type(str(path))[0] or "application/octet-stream"
            rng = self.headers.get("Range") or ""
            start, end = 0, size - 1
            partial = False
            if rng.startswith("bytes="):
                spec = rng[6:].split("-")
                try:
                    if spec[0]:
                        start = int(spec[0])
                    if len(spec) > 1 and spec[1]:
                        end = int(spec[1])
                    start = max(0, min(start, size - 1))
                    end = max(start, min(end, size - 1))
                    partial = True
                except ValueError:
                    partial = False
            length = end - start + 1
            self.send_response(206 if partial else 200)
            self.send_header("Content-Type", ctype)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(length))
            if partial:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.end_headers()
            try:
                with open(path, "rb") as fh:
                    fh.seek(start)
                    left = length
                    while left > 0:
                        chunk = fh.read(min(131072, left))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        left -= len(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_POST(self) -> None:  # noqa: N802
            try:
                url = urlparse(self.path)
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b""
                if url.path == "/api/auth/login":
                    self._login(body)
                    return
                if url.path == "/api/auth/logout":
                    self._logout()
                    return
                if url.path == "/api/user/login":
                    self._user_login(body, register=False)
                    return
                if url.path == "/api/user/register":
                    self._user_login(body, register=True)
                    return
                if url.path == "/api/user/logout":
                    self._user_logout()
                    return
                app._local.user_id = self._user_id()
                if not self._require_auth(url.path):
                    return
                status, ctype, payload = handle("POST", url.path, parse_qs(url.query), body)
                self._send(status, ctype, payload)
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"error": f"{type(exc).__name__}: {exc}"})

        def do_DELETE(self) -> None:  # noqa: N802
            try:
                url = urlparse(self.path)
                app._local.user_id = self._user_id()
                if not self._require_auth(url.path):
                    return
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
