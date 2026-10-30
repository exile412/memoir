"""命令行入口。

设计原则：一条命令做一件事，没有模型也能用（降级到本地摘要）。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any, Sequence

from . import __version__
from .config import LANG_CHOICES, Config
from .i18n import I18N
from .llm import LLMClient, LLMError
from .models import KINDS
from .persona import distill, render_profile
from .plugins import PluginContext, PluginManager
from .review import generate_review, render_review
from .scheduler import run_daemon, run_once
from .storage import Store


def _ensure_utf8_stdout() -> None:
    """Windows 控制台默认 GBK，输出日韩文会炸，强制 UTF-8。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            pass


class App:
    def __init__(self, cfg: Config, lang: str | None = None) -> None:
        self.cfg = cfg
        if lang:
            self.cfg.lang = lang
        self.i18n = I18N(self.cfg.lang)
        self.cfg.ensure_dirs()
        self.store = Store(self.cfg.db_path)
        self._pm: PluginManager | None = None
        self._logfile = self.cfg.log_path

    # ---------- 基础 ----------
    def log(self, message: str) -> None:
        try:
            with open(self._logfile, "a", encoding="utf-8") as fh:
                fh.write(message.rstrip() + "\n")
        except OSError:
            pass

    def echo(self, message: str = "") -> None:
        print(message)

    def plugins(self) -> PluginManager:
        if self._pm is None:
            ctx = PluginContext(
                config=self.cfg, store=self.store, i18n=self.i18n, logger=self.log
            )
            self._pm = PluginManager(ctx)
            self._pm.load_all()
        return self._pm

    def close(self) -> None:
        self.store.close()


# ---------------- 渲染 ----------------
def render_entries(entries: Sequence[Any], i18n: I18N, title: str) -> str:
    lines = [title, "-" * max(12, len(title))]
    for e in entries:
        stamp = e.ts[11:16] if len(e.ts) >= 16 else e.ts
        tags = f" #{e.tags}" if e.tags else ""
        mood = f" mood={e.mood:+d}" if e.mood is not None else ""
        lines.append(f"[{stamp}] #{e.id} ({e.kind}) {e.text}{tags}{mood}")
    return "\n".join(lines)


# ---------------- 命令 ----------------
def cmd_add(app: App, args: argparse.Namespace) -> int:
    text = args.text
    if text == "-":
        text = sys.stdin.read()
    text = (text or "").strip()
    if not text:
        app.echo(app.i18n.t("cli.add_empty"))
        return 1
    kind = args.kind or "event"
    entry_id = app.store.add_entry(
        text=text, kind=kind, tags=args.tags or "", mood=args.mood, source=args.source
    )
    app.echo(app.i18n.t("cli.add_ok", id=str(entry_id), kind=kind))
    pm = app.plugins()
    entry = next((e for e in app.store.recent(1) if e.id == entry_id), None)
    if entry and pm.plugins:
        pm.fire("on_entry_added", entry)
    return 0


def cmd_today(app: App, args: argparse.Namespace) -> int:
    day = args.date or date.today().isoformat()
    entries = app.store.entries_for_day(day)
    if not entries:
        app.echo(app.i18n.t("cli.no_entries"))
        return 0
    app.echo(render_entries(entries, app.i18n, app.i18n.t("cli.today_title", date=day, count=str(len(entries)))))
    return 0


def cmd_review(app: App, args: argparse.Namespace) -> int:
    day = args.date or date.today().isoformat()
    review = generate_review(
        app.store, app.cfg, app.i18n,
        day=day, force=args.force, offline=args.offline,
        persist=not args.no_write,
        allow_suspicious=args.allow_suspicious,
    )
    if review is None:
        app.echo(app.i18n.t("cli.review_none", date=day))
        return 0
    app.echo(render_review(review, app.i18n))
    if review.isolated:
        app.echo(app.i18n.t("cli.suspicious_isolated", count=str(review.isolated)))
    if review.dropped:
        app.echo(app.i18n.t("cli.review_polluted"))
    if review.model == "fallback":
        app.echo(app.i18n.t("cli.review_fallback"))
    if not args.offline:
        app.log(f"review {day} model={review.model} tokens={review.tokens}")
    pm = app.plugins()
    if pm.plugins:
        pm.fire("on_review_ready", review)
    if not args.no_write:
        app.echo(app.i18n.t("cli.review_saved", date=day))
    return 0


def cmd_persona(app: App, args: argparse.Namespace) -> int:
    if args.distill:
        learned = distill(app.store, app.cfg, app.i18n, days=args.days, offline=args.offline)
        app.echo(app.i18n.t("cli.persona_learned", count=str(len(learned))))
        app.echo("")
    app.echo(render_profile(app.store, app.i18n))
    return 0


def cmd_search(app: App, args: argparse.Namespace) -> int:
    hits = app.store.search(args.query, limit=args.limit)
    if not hits:
        app.echo(app.i18n.t("cli.search_none", query=args.query))
        return 0
    app.echo(
        render_entries(
            hits, app.i18n, app.i18n.t("cli.search_title", query=args.query, count=str(len(hits)))
        )
    )
    return 0


def cmd_stats(app: App, args: argparse.Namespace) -> int:
    s = app.store.stats()
    app.echo(app.i18n.t("cli.stats_title"))
    app.echo("-" * 12)
    for key, value in s.items():
        app.echo(f"{key:<14} {value}")
    return 0


def cmd_export(app: App, args: argparse.Namespace) -> int:
    data = app.store.export_all()
    out = Path(args.output) if args.output else app.cfg.home / f"memoir-export-{date.today().isoformat()}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    app.echo(app.i18n.t("cli.export_ok", count=str(len(data["entries"])), path=str(out)))
    return 0


def cmd_plugins(app: App, args: argparse.Namespace) -> int:
    pm = app.plugins()
    rows = pm.describe()
    if not rows:
        app.echo(app.i18n.t("cli.plugins_none", dir=str(app.cfg.plugin_dir)))
        return 0
    app.echo(app.i18n.t("cli.plugins_title"))
    app.echo("-" * 12)
    for r in rows:
        mark = "ok " if r["status"] == "ok" else "ERR"
        hooks = ",".join(r["hooks"]) or "-"
        app.echo(f"[{mark}] {r['name']}  v{r['version']}  hooks={hooks}")
        if r["description"]:
            app.echo(f"      {r['description'].strip().splitlines()[0][:100]}")
    return 0


def cmd_model(app: App, args: argparse.Namespace) -> int:
    client = LLMClient(app.cfg.model)
    ok, detail = client.health()
    if ok:
        app.echo(app.i18n.t("cli.model_ok", detail=detail))
        return 0
    app.echo(app.i18n.t("cli.model_fail", detail=detail))
    return 1


def cmd_config(app: App, args: argparse.Namespace) -> int:
    cfg = app.cfg
    app.echo(app.i18n.t("cli.config_path", path=str(cfg.config_path)))
    payload = {
        "lang": cfg.lang,
        "review_at": cfg.review_at,
        "auto_review": cfg.auto_review,
        "data_dir": str(cfg.home),
        "model": {
            "base_url": cfg.model.base_url,
            "name": cfg.model.name,
            "api_key": "***" if cfg.model.api_key else "",
            "temperature": cfg.model.temperature,
            "max_tokens": cfg.model.max_tokens,
        },
    }
    app.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    if args.edit:
        cfg.save()
        app.echo("")
        app.echo(f"written: {cfg.config_path}")
    return 0


def cmd_lang(app: App, args: argparse.Namespace) -> int:
    if not args.code:
        app.echo(app.i18n.t("cli.lang_list", langs=", ".join(app.i18n.available())))
        return 0
    if args.code not in LANG_CHOICES:
        app.echo(app.i18n.t("cli.lang_list", langs=", ".join(LANG_CHOICES)))
        return 1
    app.cfg.lang = args.code
    app.cfg.save()
    app.i18n = I18N(args.code)
    app.echo(app.i18n.t("cli.lang_set", lang=args.code))
    return 0


def cmd_daemon(app: App, args: argparse.Namespace) -> int:
    try:
        run_daemon(app.store, app.cfg, app.i18n, offline=args.offline, log=app.echo)
    except KeyboardInterrupt:
        app.echo("")
    return 0


def cmd_once(app: App, args: argparse.Namespace) -> int:
    res = run_once(app.store, app.cfg, app.i18n, day=args.date, offline=args.offline, log=app.echo)
    app.echo(app.i18n.t("cli.daemon_once"))
    for k, v in res.items():
        app.echo(f"{k:<10} {v}")
    return 0


# ---------------- 参数 ----------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="memoir",
        description="Local-first private AI memory system: record, review nightly, grow a persona.",
    )
    p.add_argument("--lang", choices=LANG_CHOICES, help="interface language")
    p.add_argument("--home", help="data directory (default ~/.memoir)")
    p.add_argument("--version", action="version", version=f"memoir {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    a = sub.add_parser("add", help="record one memory")
    a.add_argument("text", help="the memory itself; use - to read stdin")
    a.add_argument("--kind", choices=KINDS, default="event")
    a.add_argument("--tags", default="")
    a.add_argument("--mood", type=int, choices=[-2, -1, 0, 1, 2], default=None)
    a.add_argument("--source", default="cli")
    a.set_defaults(func=cmd_add)

    t = sub.add_parser("today", help="show today's entries")
    t.add_argument("--date")
    t.set_defaults(func=cmd_today)

    r = sub.add_parser("review", help="generate the nightly review")
    r.add_argument("--date")
    r.add_argument("--offline", action="store_true", help="skip the model, use local summary")
    r.add_argument("--force", action="store_true")
    r.add_argument("--no-write", action="store_true")
    r.add_argument(
        "--allow-suspicious",
        action="store_true",
        help="把疑似包含指令的记录也纳入复盘（默认隔离）",
    )
    r.set_defaults(func=cmd_review)

    pe = sub.add_parser("persona", help="show / update the persona profile")
    pe.add_argument("--distill", action="store_true", help="learn new observations first")
    pe.add_argument("--days", type=int, default=7)
    pe.add_argument("--offline", action="store_true")
    pe.set_defaults(func=cmd_persona)

    s = sub.add_parser("search", help="full-text search")
    s.add_argument("query")
    s.add_argument("-n", "--limit", type=int, default=20)
    s.set_defaults(func=cmd_search)

    st = sub.add_parser("stats", help="memory statistics")
    st.set_defaults(func=cmd_stats)

    ex = sub.add_parser("export", help="export everything as JSON")
    ex.add_argument("-o", "--output")
    ex.set_defaults(func=cmd_export)

    pl = sub.add_parser("plugins", help="list plugins")
    pl.set_defaults(func=cmd_plugins)

    m = sub.add_parser("model", help="test the model connection")
    m.set_defaults(func=cmd_model)

    c = sub.add_parser("config", help="show config")
    c.add_argument("--edit", action="store_true", help="write current config to disk")
    c.set_defaults(func=cmd_config)

    lg = sub.add_parser("lang", help="switch interface language")
    lg.add_argument("code", nargs="?", choices=LANG_CHOICES)
    lg.set_defaults(func=cmd_lang)

    d = sub.add_parser("daemon", help="run the nightly review daemon")
    d.add_argument("--offline", action="store_true")
    d.set_defaults(func=cmd_daemon)

    o = sub.add_parser("once", help="run one nightly pass now")
    o.add_argument("--date")
    o.add_argument("--offline", action="store_true")
    o.set_defaults(func=cmd_once)

    return p


def main(argv: Sequence[str] | None = None) -> int:
    _ensure_utf8_stdout()
    parser = build_parser()
    args = parser.parse_args(argv)

    cfg = Config.load()
    if getattr(args, "home", None):
        cfg.home = Path(args.home).expanduser().resolve()
    app = App(cfg, lang=getattr(args, "lang", None))
    try:
        return int(args.func(app, args) or 0)
    except LLMError as exc:
        app.echo(f"[model] {exc}")
        return 2
    except KeyboardInterrupt:
        app.echo("")
        return 130
    finally:
        app.close()


if __name__ == "__main__":
    raise SystemExit(main())
