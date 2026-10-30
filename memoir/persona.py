"""人格档案引擎。

- distill(): 从最近若干天的复盘里蒸馏人格观察，写入 persona_facts
- render_profile(): 把档案渲染成一页可读的画像
- 没有模型时降级为"直接搬运复盘里的 character 段落"，不编造
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Sequence

from .config import Config
from .i18n import I18N
from .llm import LLMClient, LLMError, extract_json
from .prompts import build_persona_messages

FACT_KEYS = ("性格", "价值观", "情感模式", "软肋", "执念", "偏好", "待人方式", "成长")


def _normalize_items(data: Any) -> list[Any] | None:
    """把模型的花式输出归一化成 [{key, value, ...}]。

    见过三种：
        {"facts": [...]}           正常
        [{"facts": [...]}]         把对象套进数组
        [{key, value}, ...]        直接就是列表
    """
    if isinstance(data, dict):
        for value in data.values():
            if isinstance(value, list):
                return value
        return None
    if isinstance(data, list):
        if len(data) == 1 and isinstance(data[0], dict):
            inner = list(data[0].values())
            if inner and isinstance(inner[0], list):
                return inner[0]
        return data
    return None


def distill(
    store: Any,
    cfg: Config,
    i18n: I18N,
    days: int = 7,
    offline: bool = False,
) -> list[dict[str, Any]]:
    reviews = [rv.to_dict() for rv in store.list_reviews(limit=days)]
    if not reviews:
        return []
    facts = [f.to_dict() for f in store.list_facts()]
    learned: list[dict[str, Any]] = []

    if not offline:
        client = LLMClient(cfg.model)
        try:
            messages = build_persona_messages(i18n, reviews, facts)
            result = client.chat(messages)
            items = _normalize_items(extract_json(result.text))
            if isinstance(items, list):
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    key = str(item.get("key") or "").strip()
                    value = str(item.get("value") or "").strip()
                    if not key or not value:
                        continue
                    learned.append(
                        {
                            "key": key,
                            "value": value,
                            "confidence": float(item.get("confidence", 0.6) or 0.6),
                            "evidence": str(item.get("evidence") or ""),
                        }
                    )
        except (LLMError, ValueError):
            learned = []

    if not learned:
        # 降级：只有当复盘真的出自模型时，才把 character 段搬运进档案。
        # 本地兜底文案（model == "fallback"）不是观察，学进去只会污染档案。
        latest = reviews[0]
        if latest.get("model") != "fallback":
            char = (latest.get("sections") or {}).get("character")
            if char:
                learned.append(
                    {
                        "key": i18n.t("persona.fallback_key"),
                        "value": char,
                        "confidence": 0.4,
                        "evidence": latest.get("day", ""),
                    }
                )

    for item in learned:
        store.upsert_fact(
            key=item["key"],
            value=item["value"],
            confidence=item["confidence"],
            evidence=item["evidence"],
        )
    return learned


def render_profile(store: Any, i18n: I18N) -> str:
    facts = store.list_facts()
    title = i18n.t("persona.title")
    if not facts:
        return title + "\n" + "=" * len(title) + "\n\n" + i18n.t("persona.empty") + "\n"

    grouped: dict[str, list[Any]] = {}
    for f in facts:
        grouped.setdefault(f.key, []).append(f)

    lines = [title, "=" * len(title), ""]
    for key, items in grouped.items():
        lines.append(f"## {key}")
        for f in items:
            ev = f"（{f.evidence}）" if f.evidence else ""
            lines.append(f"- {f.value}  · 置信度 {f.confidence:.2f}{ev}")
        lines.append("")

    snap = store.latest_snapshot()
    if snap:
        day, traits, note = snap
        lines.append(i18n.t("persona.snapshot", date=day))
        if note:
            lines.append(note)
        lines.append("")

    stats = store.stats()
    lines.append(
        i18n.t(
            "persona.stats",
            entries=str(stats["entries"]),
            days=str(stats["days"]),
            reviews=str(stats["reviews"]),
        )
    )
    return "\n".join(lines).rstrip() + "\n"
