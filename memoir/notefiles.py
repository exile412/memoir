"""记事本模式：记忆存成每天一个 Markdown 文件，直接拿记事本改。

设计取舍：
- 文件是给人看的，也是给人改的，格式必须简单到不会写错
- 数据库仍然是检索索引，但同步以「文件」为准（文件改了库跟着改）
- 匹配靠 (日期, 时间, 正文)，不做 id——手改文件时没人愿意看 id
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any

KIND_TO_CN = {"event": "事件", "thought": "想法", "feeling": "情绪", "note": "备注"}
CN_TO_KIND = {v: k for k, v in KIND_TO_CN.items()}

HEAD = re.compile(r"^#\s+(\d{4}-\d{2}-\d{2})\s*$")
ITEM = re.compile(r"^##\s+(\d{1,2}:\d{2})\s*(?:[·\-—]?\s*)(\S+)?\s*$")


def note_path(notes_dir: Path, day: str) -> Path:
    return Path(notes_dir) / f"{day}.md"


def render_day(entries: list[Any], day: str) -> str:
    """把一天的记录渲染成记事本友好的 Markdown。"""
    lines = [f"# {day}", ""]
    if not entries:
        lines.append("<!-- 这一天还没有记录。在下面按格式加一条即可： -->")
        lines.append("<!-- ## 22:30 事件 \\ 写的内容 -->")
        lines.append("")
    for e in entries:
        stamp = e.ts[11:16] if len(e.ts) >= 16 else e.ts
        kind_cn = KIND_TO_CN.get(e.kind, e.kind)
        lines.append(f"## {stamp} {kind_cn}")
        for para in str(e.text).split("\n"):
            lines.append(para)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def parse_day(text: str, fallback_day: str) -> list[dict[str, str]]:
    """从 Markdown 里解析出条目。解析不了的行直接忽略，不报错。"""
    day = fallback_day
    items: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    body: list[str] = []

    def flush() -> None:
        nonlocal current, body
        if current is not None:
            content = "\n".join(body).strip()
            if content:
                current["text"] = content
                items.append(current)
        current, body = None, []

    for raw in text.splitlines():
        line = raw.rstrip()
        m_head = HEAD.match(line.strip())
        if m_head:
            flush()
            day = m_head.group(1)
            continue
        m_item = ITEM.match(line.strip())
        if m_item:
            flush()
            stamp = m_item.group(1).zfill(5)
            kind_cn = (m_item.group(2) or "事件").strip()
            current = {
                "day": day,
                "ts": f"{day}T{stamp}:00",
                "kind": CN_TO_KIND.get(kind_cn, kind_cn),
            }
            body = []
            continue
        if current is not None:
            if line.strip().startswith("<!--"):
                continue
            body.append(line)
    flush()
    return items


def export_all(store: Any, notes_dir: Path) -> int:
    """把库里的记录写成文件。已存在的文件不覆盖（除非内容为空）。"""
    notes_dir = Path(notes_dir)
    notes_dir.mkdir(parents=True, exist_ok=True)
    days = store.days_with_entries(limit=100000)
    today = date.today().isoformat()
    if today not in days:
        days.append(today)
    written = 0
    for day in days:
        path = note_path(notes_dir, day)
        entries = store.entries_for_day(day)
        if path.exists() and path.stat().st_size > 0 and entries:
            # 文件已在，库里也有——不覆盖，避免冲掉手工改动
            continue
        path.write_text(render_day(entries, day), encoding="utf-8")
        written += 1
    return written


def sync_from_dir(store: Any, notes_dir: Path) -> dict[str, int]:
    """以文件为准合并进库：新增 / 更新 / 删除。"""
    notes_dir = Path(notes_dir)
    if not notes_dir.is_dir():
        return {"added": 0, "updated": 0, "removed": 0, "files": 0}

    stats = {"added": 0, "updated": 0, "removed": 0, "files": 0}
    for path in sorted(notes_dir.glob("*.md")):
        fallback = path.stem if re.match(r"^\d{4}-\d{2}-\d{2}$", path.stem) else date.today().isoformat()
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        items = parse_day(text, fallback)
        stats["files"] += 1

        by_day: dict[str, list[dict[str, str]]] = {}
        for it in items:
            by_day.setdefault(it["day"], []).append(it)

        for day, wanted in by_day.items():
            existing = store.entries_for_day(day)
            pool = list(existing)

            for it in wanted:
                match = None
                for e in pool:
                    stamp = e.ts[11:16] if len(e.ts) >= 16 else ""
                    if stamp == it["ts"][11:16]:
                        match = e
                        break
                if match is None:
                    store.add_entry(
                        text=it["text"], kind=it["kind"], source="notepad",
                        meta={"from": "notepad"},
                    )
                    stats["added"] += 1
                else:
                    pool.remove(match)
                    if match.text.strip() != it["text"].strip():
                        store.update_entry(match.id, text=it["text"], kind=it["kind"])
                        stats["updated"] += 1

            for leftover in pool:
                store.delete_entry(leftover.id)
                stats["removed"] += 1
    return stats
