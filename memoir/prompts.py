"""提示词构建。

所有模板来自 locales/*.json 的 prompts 段，换语言=换语言包，不改代码。
"""

from __future__ import annotations

from typing import Any, Sequence

from .i18n import I18N
from .models import Entry

REVIEW_KEYS = ("events", "thoughts", "thinking", "character", "closing")


def _fmt_entries(entries: Sequence[Entry]) -> str:
    lines = []
    for e in entries:
        tag = f"#{e.tags}" if e.tags else ""
        lines.append(f"[{e.ts[11:16] if len(e.ts) >= 16 else e.ts}] ({e.kind}) {e.text} {tag}".rstrip())
    return "\n".join(lines) if lines else "-"


def _fmt_persona(facts: Sequence[dict[str, Any]]) -> str:
    if not facts:
        return "-"
    return "\n".join(
        f"- [{f.get('key', '?')}] {f.get('value', '')} (置信度 {float(f.get('confidence', 0.5)):.2f})"
        for f in facts
    )


def build_review_messages(
    i18n: I18N,
    day: str,
    entries: Sequence[Entry],
    facts: Sequence[dict[str, Any]],
) -> list[dict[str, str]]:
    system = i18n.t("prompts.review_system")
    user = i18n.t(
        "prompts.review_user",
        date=day,
        count=str(len(entries)),
        entries=_fmt_entries(entries),
        persona=_fmt_persona(facts),
        schema=i18n.t("prompts.review_schema"),
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def build_persona_messages(
    i18n: I18N,
    reviews: Sequence[dict[str, Any]],
    facts: Sequence[dict[str, Any]],
) -> list[dict[str, str]]:
    system = i18n.t("prompts.persona_system")
    blocks = []
    for rv in reviews:
        secs = rv.get("sections", {})
        body = "\n".join(f"- {k}: {v}" for k, v in secs.items() if v)
        blocks.append(f"### {rv.get('day')}\n{body or '(空)'}")
    user = i18n.t(
        "prompts.persona_user",
        reviews="\n\n".join(blocks) or "-",
        persona=_fmt_persona(facts),
        schema=i18n.t("prompts.persona_schema"),
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]
