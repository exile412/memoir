"""夜间复盘引擎。

两种模式：
- 有模型：让模型按 sections 结构生成，解析 JSON
- 无模型：本地统计 + 摘录兜底，保证离线也能出日报
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import date as date_cls
from datetime import datetime
from typing import Any, Sequence

from .config import Config
from .i18n import I18N
from .llm import LLMClient, LLMError, extract_json, unwrap_object
from .models import Entry, Review
from .prompts import REVIEW_KEYS, build_review_messages
from .safety import contains_pollution, looks_like_injection


_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def clean_text(text: str) -> str:
    """剥掉控制字符（含 ANSI 转义），防止模型输出把终端搞乱。"""
    return _CONTROL_CHARS.sub("", str(text))


def _today() -> str:
    return date_cls.today().isoformat()


def _fallback_sections(i18n: I18N, entries: Sequence[Entry]) -> dict[str, str]:
    """没有模型时的本地摘要：只做可验证的统计，不编造结论。"""
    kinds = Counter(e.kind for e in entries)
    first = entries[0].ts[11:16] if entries and len(entries[0].ts) >= 16 else "?"
    last = entries[-1].ts[11:16] if entries and len(entries[-1].ts) >= 16 else "?"

    def pick(kind: str, limit: int = 5) -> str:
        picked = [e.text for e in entries if e.kind == kind][-limit:]
        return "; ".join(picked) if picked else i18n.t("report.none")

    return {
        "events": pick("event"),
        "thoughts": pick("thought"),
        "thinking": i18n.t(
            "report.fallback_thinking",
            kinds=", ".join(f"{k}×{v}" for k, v in kinds.items()),
        ),
        "character": i18n.t("report.fallback_character"),
        "closing": i18n.t(
            "report.fallback_closing",
            count=str(len(entries)),
            first=first,
            last=last,
        ),
    }


def generate_review(
    store: Any,
    cfg: Config,
    i18n: I18N,
    day: str | None = None,
    force: bool = False,
    offline: bool = False,
    persist: bool = True,
    allow_suspicious: bool = False,
) -> Review | None:
    day = day or _today()
    all_entries = store.entries_for_day(day)
    if not all_entries:
        return None

    # 输入侧防线：像指令的记录默认不参与复盘。
    # 这不是「大概能防住」，而是确定性地不让它进 prompt。
    suspicious = [e for e in all_entries if looks_like_injection(e.text)]
    if allow_suspicious:
        entries = all_entries
        isolated = 0
    else:
        entries = [e for e in all_entries if not looks_like_injection(e.text)]
        isolated = len(suspicious)

    facts = [f.to_dict() for f in store.list_facts()]
    sections: dict[str, str] = {}
    model_name = "fallback"
    tokens = 0
    dropped = False

    if not offline and entries:
        client = LLMClient(cfg.model)
        try:
            messages = build_review_messages(i18n, day, entries, facts)
            result = client.chat(messages)
            data = unwrap_object(extract_json(result.text))
            if isinstance(data, dict):
                candidate: dict[str, str] = {}
                for key in REVIEW_KEYS:
                    value = data.get(key)
                    if isinstance(value, list):
                        value = "; ".join(str(v) for v in value)
                    if value:
                        candidate[key] = clean_text(str(value)).strip()
                # 输出侧防线：就算漏网的记录混进去了，正文里出现指令腔也丢弃
                if candidate and contains_pollution(candidate, [e.text for e in suspicious]):
                    dropped = True
                elif candidate:
                    sections = candidate
                    model_name = result.model
                    tokens = result.tokens
        except LLMError:
            sections = {}

    if not sections:
        sections = _fallback_sections(i18n, entries or all_entries)

    summary = sections.get("closing") or sections.get("events") or ""
    review = Review(
        day=day,
        locale=i18n.lang,
        model=model_name,
        sections=sections,
        summary=summary,
        created_at=datetime.now().isoformat(timespec="seconds"),
        entries_count=len(all_entries),
        tokens=tokens,
        isolated=isolated,
        dropped=dropped,
    )
    if persist:
        store.save_review(review)
    return review


def render_review(review: Review, i18n: I18N) -> str:
    """把复盘渲染成给人看的文本。"""
    title = i18n.t("report.title", date=review.day)
    lines = [title, "=" * len(title), ""]
    label_map = {
        "events": "report.sections.events",
        "thoughts": "report.sections.thoughts",
        "thinking": "report.sections.thinking",
        "character": "report.sections.character",
        "closing": "report.sections.closing",
    }
    for key, i18n_key in label_map.items():
        value = review.sections.get(key)
        if not value:
            continue
        lines.append(f"【{i18n.t(i18n_key)}】")
        lines.append(value)
        lines.append("")
    meta = i18n.t(
        "report.meta",
        count=str(review.entries_count),
        model=review.model,
        locale=review.locale,
    )
    lines.append(meta)
    return "\n".join(lines).rstrip() + "\n"
