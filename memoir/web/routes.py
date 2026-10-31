"""路由分发。手写而不是用框架，是为了保持零依赖。"""

from __future__ import annotations

import json
import mimetypes
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable

from ..persona import distill, render_profile
from ..review import generate_review, render_review

JSON_T = "application/json; charset=utf-8"


def _json(obj: Any, status: int = 200) -> tuple[int, str, bytes]:
    return status, JSON_T, json.dumps(obj, ensure_ascii=False).encode("utf-8")


def _text(s: str, status: int = 200) -> tuple[int, str, bytes]:
    return status, "text/plain; charset=utf-8", s.encode("utf-8")


def _entry_json(e: Any) -> dict[str, Any]:
    return {
        "id": e.id,
        "ts": e.ts,
        "day": e.day,
        "kind": e.kind,
        "text": e.text,
        "tags": e.tags,
        "title": (e.meta or {}).get("title", ""),
        "mood": e.mood,
        "source": e.source,
        "meta": e.meta or {},
    }


def dispatch(app: Any, method: str, path: str, query: dict[str, list[str]],
             body: bytes, static_dir: Path) -> tuple[int, str, bytes]:
    # ---- 静态资源 ----
    if path == "/" or path == "/index.html":
        f = static_dir / "index.html"
        if not f.exists():
            return _text("前端未安装：缺少 static/index.html", 500)
        return 200, "text/html; charset=utf-8", f.read_bytes()

    if path.startswith("/static/"):
        rel = path[len("/static/"):].replace("..", "")
        f = static_dir / rel
        if not f.is_file():
            return _text("not found", 404)
        ctype = mimetypes.guess_type(str(f))[0] or "application/octet-stream"
        if f.suffix in {".js", ".mjs"}:
            ctype = "application/javascript; charset=utf-8"
        elif f.suffix == ".css":
            ctype = "text/css; charset=utf-8"
        return 200, ctype, f.read_bytes()

    # ---- API ----
    if not path.startswith("/api/"):
        return _text("not found", 404)

    # 认证相关（不需要登录就能访问）
    if method == "GET" and path == "/api/auth/status":
        return _json({"enabled": app.auth.enabled})

    payload: dict[str, Any] = {}
    if body:
        try:
            payload = json.loads(body.decode("utf-8"))
        except Exception:  # noqa: BLE001
            return _json({"error": "请求体不是合法 JSON"}, 400)

    route = path[len("/api/"):].strip("/")

    if method == "GET" and route == "bootstrap":
        from .app import build_bootstrap

        return _json(build_bootstrap(app))

    if method == "GET" and route == "entries":
        day = query.get("day", [""])[0]
        q = query.get("q", [""])[0].strip()
        kind = query.get("kind", [""])[0].strip()
        limit = int(query.get("limit", ["100"])[0])
        if q:
            rows = app.store.search(q, limit=limit)
            rows = list(reversed(rows))
        elif day:
            rows = list(reversed(app.store.entries_for_day(day)))
        else:
            rows = app.store.recent(limit)
        if kind:
            rows = [e for e in rows if e.kind == kind]
        return _json({"entries": [_entry_json(e) for e in rows]})

    if method == "POST" and route == "entries":
        text = (payload.get("text") or "").strip()
        if not text:
            return _json({"error": "内容为空"}, 400)
        kind = payload.get("kind") or "event"
        mode = payload.get("mode") or "raw"          # raw | polished | organized
        make_title = bool(payload.get("autoTitle", True))
        tags = (payload.get("tags") or "").strip()

        final_text = text
        if mode == "polished":
            final_text = app.polish(text)
        elif mode == "organized":
            final_text = app.summarize(text)

        title = app.make_title(final_text) if make_title else ""
        meta = {"title": title, "mode": mode, "original": text if mode != "raw" else ""}
        entry_id = app.store.add_entry(
            text=final_text, kind=kind, tags=tags, source="web", meta=meta
        )
        row = next((e for e in app.store.recent(5) if e.id == entry_id), None)
        return _json({"ok": True, "entry": _entry_json(row) if row else None})

    if method == "DELETE" and route.startswith("entries/"):
        try:
            eid = int(route.split("/")[1])
        except (IndexError, ValueError):
            return _json({"error": "id 不合法"}, 400)
        return _json({"ok": app.store.delete_entry(eid)})

    if method == "POST" and route == "polish":
        text = (payload.get("text") or "").strip()
        if not text:
            return _json({"error": "内容为空"}, 400)
        return _json({"text": app.polish(text)})

    if method == "POST" and route == "summarize":
        text = (payload.get("text") or "").strip()
        if not text:
            return _json({"error": "内容为空"}, 400)
        return _json({"text": app.summarize(text)})

    if method == "GET" and route == "review":
        day = query.get("day", [date.today().isoformat()])[0]
        rv = app.store.get_review(day)
        if not rv:
            return _json({"day": day, "review": None})
        return _json({
            "day": day,
            "review": {"sections": rv.sections, "model": rv.model,
                       "entries": rv.entries_count, "createdAt": rv.created_at},
        })

    if method == "POST" and route == "review":
        day = payload.get("day") or date.today().isoformat()
        offline = bool(payload.get("offline", False))
        rv = generate_review(app.store, app.cfg, app.i18n, day=day, offline=offline)
        if rv is None:
            return _json({"day": day, "review": None, "message": "这一天没有记录"})
        return _json({
            "day": day,
            "review": {"sections": rv.sections, "model": rv.model,
                       "entries": rv.entries_count, "isolated": rv.isolated,
                       "dropped": rv.dropped},
            "text": render_review(rv, app.i18n),
        })

    if method == "GET" and route == "persona":
        return _json({"text": render_profile(app.store, app.i18n)})

    if method == "POST" and route == "persona/distill":
        learned = distill(app.store, app.cfg, app.i18n, days=7)
        return _json({"learned": len(learned), "text": render_profile(app.store, app.i18n)})

    if method == "GET" and route == "settings":
        m = app.cfg.model
        return _json({
            "lang": app.cfg.lang,
            "reviewAt": app.cfg.review_at,
            "model": {
                "baseUrl": m.base_url, "name": m.name,
                "apiKey": "***" if m.api_key else "",
                "temperature": m.temperature, "maxTokens": m.max_tokens, "timeout": m.timeout,
            },
            "wallpaperDir": app.cfg.extra.get("wallpaper_dir", ""),
        })

    if method == "POST" and route == "settings":
        m = app.cfg.model
        body_m = payload.get("model") or {}
        if body_m.get("baseUrl"):
            m.base_url = str(body_m["baseUrl"]).strip()
        if body_m.get("name"):
            m.name = str(body_m["name"]).strip()
        if body_m.get("apiKey") and body_m["apiKey"] != "***":
            m.api_key = str(body_m["apiKey"]).strip()
        for key, cast in (("temperature", float), ("maxTokens", int), ("timeout", int)):
            if body_m.get(key) is not None:
                setattr(m, "max_tokens" if key == "maxTokens" else key, cast(body_m[key]))
        if payload.get("wallpaperDir") is not None:
            app.cfg.extra["wallpaper_dir"] = str(payload["wallpaperDir"]).strip()
        if payload.get("lang"):
            app.cfg.lang = str(payload["lang"])
        path = app.cfg.save()
        return _json({"ok": True, "savedTo": str(path)})

    if method == "POST" and route == "auth/setup":
        if app.auth.enabled:
            return _json({"error": "密码已设置，不能再设一次"}, 400)
        pwd = str(payload.get("password") or "").strip()
        if len(pwd) < 4:
            return _json({"error": "密码至少 4 位"}, 400)
        app.auth.set_password(pwd)
        return _json({"ok": True, "enabled": True})

    if method == "POST" and route == "auth/reset":
        # 只能在未登录状态下清空（会要求当前密码），这里留作 CLI 辅助
        return _json({"error": "请在服务器上删除 ~/.memoir/auth.json 来重置"}, 400)

    if method == "POST" and route == "notes/sync":
        from ..notefiles import sync_from_dir

        d = app.cfg.home / "notes"
        stats = sync_from_dir(app.store, d)
        return _json({"ok": True, "dir": str(d), **stats})

    if method == "POST" and route == "notes/export":
        from ..notefiles import export_all

        d = app.cfg.home / "notes"
        written = export_all(app.store, d)
        return _json({"ok": True, "dir": str(d), "written": written})

    if method == "POST" and route == "notes/open":
        import os
        import subprocess
        import sys as _sys

        d = app.cfg.home / "notes"
        d.mkdir(parents=True, exist_ok=True)
        try:
            if _sys.platform == "win32":
                os.startfile(str(d))  # type: ignore[attr-defined]
            elif _sys.platform == "darwin":
                subprocess.Popen(["open", str(d)])
            else:
                subprocess.Popen(["xdg-open", str(d)])
        except Exception as exc:  # noqa: BLE001
            return _json({"ok": False, "dir": str(d), "error": str(exc)})
        return _json({"ok": True, "dir": str(d)})

    if method == "POST" and route == "model/test":
        from ..llm import LLMClient

        ok, detail = LLMClient(app.cfg.model).health()
        return _json({"ok": ok, "detail": detail})

    if method == "GET" and route == "export":
        data = app.store.export_all()
        return _json(data)

    if method == "GET" and route == "wallpapers":
        from .app import list_wallpapers

        return _json({"wallpapers": list_wallpapers(app)})

    if method == "GET" and route == "wallpaper":
        from .app import wallpaper_path

        wid = query.get("id", [""])[0]
        p = wallpaper_path(app, wid)
        if not p:
            return _text("not found", 404)
        ctype = mimetypes.guess_type(str(p))[0] or "image/jpeg"
        return 200, ctype, p.read_bytes()

    if method == "HEAD" and route == "wallpaper-meta":
        from .app import wallpaper_path

        wid = query.get("id", [""])[0]
        p = wallpaper_path(app, wid)
        if not p:
            return _json({"error": "not found"}, 404)
        return _json({"size": p.stat().st_size, "type": p.suffix.lower()})

    return _json({"error": f"未知接口 {method} /api/{route}"}, 404)
