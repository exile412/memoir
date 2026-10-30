"""数据模型。全部是纯 dataclass，便于插件序列化和跨语言导出。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

KINDS = ("event", "thought", "feeling", "note")
KIND_LABEL = {
    "event": "event",
    "thought": "thought",
    "feeling": "feeling",
    "note": "note",
}


@dataclass
class Entry:
    """一条记忆。"""

    id: int | None
    ts: str
    day: str
    kind: str
    text: str
    tags: str = ""
    mood: int | None = None
    source: str = "cli"
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Review:
    """一份夜间复盘。"""

    day: str
    locale: str
    model: str
    sections: dict[str, str] = field(default_factory=dict)
    summary: str = ""
    created_at: str = ""
    entries_count: int = 0
    tokens: int = 0
    # 以下两个只在内存里用，不写库：本轮隔离了几条可疑记录、是否因污染被丢弃
    isolated: int = 0
    dropped: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PersonaFact:
    """人格档案里的一条观察。"""

    id: int | None
    key: str
    value: str
    confidence: float = 0.5
    evidence: str = ""
    updated_at: str = ""
    active: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
