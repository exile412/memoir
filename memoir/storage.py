"""存储层：SQLite 单文件 + FTS5 检索。

设计原则：
- 一个文件装下全部记忆（默认 ~/.memoir/memoir.db），拷走就是全部搬迁
- 中文检索走 trigram 分词，1~2 字查询自动退回 LIKE
- 任何写操作都是追加或按主键更新，不整表重写
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from .config import restrict_permissions
from .models import Entry, PersonaFact, Review

SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    ts      TEXT NOT NULL,
    day     TEXT NOT NULL,
    kind    TEXT NOT NULL DEFAULT 'event',
    text    TEXT NOT NULL,
    tags    TEXT NOT NULL DEFAULT '',
    mood    INTEGER,
    source  TEXT NOT NULL DEFAULT 'cli',
    meta    TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_entries_day  ON entries(day);
CREATE INDEX IF NOT EXISTS idx_entries_kind ON entries(kind);

CREATE VIRTUAL TABLE IF NOT EXISTS entries_fts USING fts5(
    text, tags,
    content='entries',
    content_rowid='id',
    tokenize='trigram'
);

CREATE TRIGGER IF NOT EXISTS entries_ai AFTER INSERT ON entries BEGIN
    INSERT INTO entries_fts(rowid, text, tags) VALUES (new.id, new.text, new.tags);
END;
CREATE TRIGGER IF NOT EXISTS entries_ad AFTER DELETE ON entries BEGIN
    INSERT INTO entries_fts(entries_fts, rowid, text, tags) VALUES('delete', old.id, old.text, old.tags);
END;
CREATE TRIGGER IF NOT EXISTS entries_au AFTER UPDATE ON entries BEGIN
    INSERT INTO entries_fts(entries_fts, rowid, text, tags) VALUES('delete', old.id, old.text, old.tags);
    INSERT INTO entries_fts(rowid, text, tags) VALUES (new.id, new.text, new.tags);
END;

CREATE TABLE IF NOT EXISTS reviews (
    day           TEXT PRIMARY KEY,
    locale        TEXT NOT NULL DEFAULT 'zh',
    model         TEXT NOT NULL DEFAULT '',
    sections      TEXT NOT NULL DEFAULT '{}',
    summary       TEXT NOT NULL DEFAULT '',
    entries_count INTEGER NOT NULL DEFAULT 0,
    tokens        INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reviews_history (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    day        TEXT NOT NULL,
    locale     TEXT NOT NULL DEFAULT 'zh',
    model      TEXT NOT NULL DEFAULT '',
    sections   TEXT NOT NULL DEFAULT '{}',
    summary    TEXT NOT NULL DEFAULT '',
    entries_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_history_day ON reviews_history(day);

CREATE TABLE IF NOT EXISTS persona_facts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    key        TEXT NOT NULL,
    value      TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.5,
    evidence   TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL,
    active     INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_facts_key ON persona_facts(key);

CREATE TABLE IF NOT EXISTS persona_snapshots (
    day     TEXT PRIMARY KEY,
    traits  TEXT NOT NULL DEFAULT '{}',
    note    TEXT NOT NULL DEFAULT ''
);
"""


def _now() -> datetime:
    return datetime.now()


class Store:
    def __init__(self, db_path: str | Path) -> None:
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(SCHEMA)
        self.conn.commit()
        restrict_permissions(self.path)

    # ---------------- 基础 ----------------
    def close(self) -> None:
        with self._lock:
            self.conn.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # ---------------- 记忆 ----------------
    def add_entry(
        self,
        text: str,
        kind: str = "event",
        tags: str = "",
        mood: int | None = None,
        source: str = "cli",
        ts: datetime | None = None,
        meta: dict[str, Any] | None = None,
    ) -> int:
        text = (text or "").strip()
        if not text:
            raise ValueError("empty entry")
        when = ts or _now()
        row = (
            when.isoformat(timespec="seconds"),
            when.strftime("%Y-%m-%d"),
            kind,
            text,
            tags,
            mood,
            source,
            json.dumps(meta or {}, ensure_ascii=False),
        )
        with self._lock:
            cur = self.conn.execute(
                "INSERT INTO entries(ts, day, kind, text, tags, mood, source, meta)"
                " VALUES (?,?,?,?,?,?,?,?)",
                row,
            )
            self.conn.commit()
            return int(cur.lastrowid)

    @staticmethod
    def _to_entry(r: sqlite3.Row) -> Entry:
        try:
            meta = json.loads(r["meta"] or "{}")
        except json.JSONDecodeError:
            meta = {}
        return Entry(
            id=r["id"],
            ts=r["ts"],
            day=r["day"],
            kind=r["kind"],
            text=r["text"],
            tags=r["tags"] or "",
            mood=r["mood"],
            source=r["source"] or "cli",
            meta=meta,
        )

    def entries_for_day(self, day: str, kinds: Iterable[str] | None = None) -> list[Entry]:
        sql = "SELECT * FROM entries WHERE day = ?"
        params: list[Any] = [day]
        if kinds:
            ks = list(kinds)
            sql += f" AND kind IN ({','.join('?' * len(ks))})"
            params.extend(ks)
        sql += " ORDER BY ts ASC, id ASC"
        with self._lock:
            rows = self.conn.execute(sql, params).fetchall()
        return [self._to_entry(r) for r in rows]

    def entries_between(self, start_day: str, end_day: str) -> list[Entry]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM entries WHERE day >= ? AND day <= ? ORDER BY ts ASC, id ASC",
                (start_day, end_day),
            ).fetchall()
        return [self._to_entry(r) for r in rows]

    def recent(self, limit: int = 20) -> list[Entry]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM entries ORDER BY ts DESC, id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._to_entry(r) for r in rows]

    def days_with_entries(self, limit: int = 30) -> list[str]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT day, COUNT(*) c FROM entries GROUP BY day ORDER BY day DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [r["day"] for r in rows]

    def search(self, query: str, limit: int = 20) -> list[Entry]:
        q = (query or "").strip()
        if not q:
            return []
        with self._lock:
            if len(q) >= 3:
                try:
                    rows = self.conn.execute(
                        "SELECT e.* FROM entries_fts f JOIN entries e ON e.id = f.rowid"
                        " WHERE entries_fts MATCH ? ORDER BY rank LIMIT ?",
                        ('"' + q.replace('"', '""') + '"', limit),
                    ).fetchall()
                    if rows:
                        return [self._to_entry(r) for r in rows]
                except sqlite3.OperationalError:
                    pass
            like = f"%{q}%"
            rows = self.conn.execute(
                "SELECT * FROM entries WHERE text LIKE ? OR tags LIKE ?"
                " ORDER BY ts DESC LIMIT ?",
                (like, like, limit),
            ).fetchall()
        return [self._to_entry(r) for r in rows]

    def delete_entry(self, entry_id: int) -> bool:
        with self._lock:
            cur = self.conn.execute("DELETE FROM entries WHERE id = ?", (entry_id,))
            self.conn.commit()
            return cur.rowcount > 0

    def count_entries(self) -> int:
        with self._lock:
            return int(self.conn.execute("SELECT COUNT(*) c FROM entries").fetchone()["c"])

    # ---------------- 复盘 ----------------
    def save_review(self, review: Review) -> None:
        """保存复盘。同一天重跑时，把旧版本先搬进 reviews_history，不丢历史。"""
        with self._lock:
            old = self.conn.execute(
                "SELECT * FROM reviews WHERE day = ?", (review.day,)
            ).fetchone()
            if old:
                self.conn.execute(
                    "INSERT INTO reviews_history(day, locale, model, sections, summary, entries_count, created_at)"
                    " VALUES (?,?,?,?,?,?,?)",
                    (
                        old["day"], old["locale"], old["model"], old["sections"],
                        old["summary"], old["entries_count"], old["created_at"],
                    ),
                )
            self.conn.execute(
                "INSERT INTO reviews(day, locale, model, sections, summary, entries_count, tokens, created_at)"
                " VALUES (?,?,?,?,?,?,?,?)"
                " ON CONFLICT(day) DO UPDATE SET locale=excluded.locale, model=excluded.model,"
                " sections=excluded.sections, summary=excluded.summary,"
                " entries_count=excluded.entries_count, tokens=excluded.tokens,"
                " created_at=excluded.created_at",
                (
                    review.day,
                    review.locale,
                    review.model,
                    json.dumps(review.sections, ensure_ascii=False),
                    review.summary,
                    review.entries_count,
                    review.tokens,
                    review.created_at or _now().isoformat(timespec="seconds"),
                ),
            )
            self.conn.commit()

    def get_review(self, day: str) -> Review | None:
        with self._lock:
            r = self.conn.execute("SELECT * FROM reviews WHERE day = ?", (day,)).fetchone()
        if not r:
            return None
        try:
            sections = json.loads(r["sections"] or "{}")
        except json.JSONDecodeError:
            sections = {}
        return Review(
            day=r["day"],
            locale=r["locale"],
            model=r["model"],
            sections=sections,
            summary=r["summary"] or "",
            created_at=r["created_at"] or "",
            entries_count=r["entries_count"] or 0,
            tokens=r["tokens"] or 0,
        )

    def get_review_history(self, day: str, limit: int = 20) -> list[Review]:
        """某一天被覆盖掉的旧复盘。"""
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM reviews_history WHERE day = ? ORDER BY id DESC LIMIT ?",
                (day, limit),
            ).fetchall()
        out: list[Review] = []
        for r in rows:
            try:
                sections = json.loads(r["sections"] or "{}")
            except json.JSONDecodeError:
                sections = {}
            out.append(
                Review(
                    day=r["day"], locale=r["locale"], model=r["model"],
                    sections=sections, summary=r["summary"] or "",
                    created_at=r["created_at"] or "",
                    entries_count=r["entries_count"] or 0,
                )
            )
        return out

    def list_reviews(self, limit: int = 10) -> list[Review]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT day FROM reviews ORDER BY day DESC LIMIT ?", (limit,)
            ).fetchall()
        return [rv for rv in (self.get_review(r["day"]) for r in rows) if rv]

    # ---------------- 人格 ----------------
    def upsert_fact(
        self,
        key: str,
        value: str,
        confidence: float = 0.5,
        evidence: str = "",
    ) -> int:
        now = _now().isoformat(timespec="seconds")
        with self._lock:
            row = self.conn.execute(
                "SELECT id, confidence FROM persona_facts WHERE key = ? AND value = ? AND active = 1",
                (key, value),
            ).fetchone()
            if row:
                new_conf = min(0.99, max(float(row["confidence"]), confidence) + 0.05)
                self.conn.execute(
                    "UPDATE persona_facts SET confidence = ?, updated_at = ?,"
                    " evidence = CASE WHEN ? = '' THEN evidence ELSE ? END WHERE id = ?",
                    (new_conf, now, evidence, evidence, row["id"]),
                )
                self.conn.commit()
                return int(row["id"])
            cur = self.conn.execute(
                "INSERT INTO persona_facts(key, value, confidence, evidence, updated_at, active)"
                " VALUES (?,?,?,?,?,1)",
                (key, value, confidence, evidence, now),
            )
            self.conn.commit()
            return int(cur.lastrowid)

    def list_facts(self, active_only: bool = True) -> list[PersonaFact]:
        sql = "SELECT * FROM persona_facts" + (" WHERE active = 1" if active_only else "")
        sql += " ORDER BY confidence DESC, updated_at DESC"
        with self._lock:
            rows = self.conn.execute(sql).fetchall()
        return [
            PersonaFact(
                id=r["id"],
                key=r["key"],
                value=r["value"],
                confidence=r["confidence"],
                evidence=r["evidence"] or "",
                updated_at=r["updated_at"] or "",
                active=bool(r["active"]),
            )
            for r in rows
        ]

    def deactivate_fact(self, fact_id: int) -> bool:
        with self._lock:
            cur = self.conn.execute(
                "UPDATE persona_facts SET active = 0 WHERE id = ?", (fact_id,)
            )
            self.conn.commit()
            return cur.rowcount > 0

    def save_snapshot(self, day: str, traits: dict[str, Any], note: str = "") -> None:
        with self._lock:
            self.conn.execute(
                "INSERT INTO persona_snapshots(day, traits, note) VALUES (?,?,?)"
                " ON CONFLICT(day) DO UPDATE SET traits=excluded.traits, note=excluded.note",
                (day, json.dumps(traits, ensure_ascii=False), note),
            )
            self.conn.commit()

    def latest_snapshot(self) -> tuple[str, dict[str, Any], str] | None:
        with self._lock:
            r = self.conn.execute(
                "SELECT * FROM persona_snapshots ORDER BY day DESC LIMIT 1"
            ).fetchone()
        if not r:
            return None
        try:
            traits = json.loads(r["traits"] or "{}")
        except json.JSONDecodeError:
            traits = {}
        return r["day"], traits, r["note"] or ""

    # ---------------- 统计 / 导出 ----------------
    def stats(self) -> dict[str, Any]:
        with self._lock:
            total = self.count_entries()
            days = int(
                self.conn.execute("SELECT COUNT(DISTINCT day) c FROM entries").fetchone()["c"]
            )
            reviews = int(self.conn.execute("SELECT COUNT(*) c FROM reviews").fetchone()["c"])
            facts = int(
                self.conn.execute(
                    "SELECT COUNT(*) c FROM persona_facts WHERE active = 1"
                ).fetchone()["c"]
            )
            first = self.conn.execute("SELECT MIN(day) d FROM entries").fetchone()["d"]
            last = self.conn.execute("SELECT MAX(day) d FROM entries").fetchone()["d"]
        return {
            "entries": total,
            "days": days,
            "reviews": reviews,
            "persona_facts": facts,
            "first_day": first,
            "last_day": last,
        }

    def export_all(self) -> dict[str, Any]:
        with self._lock:
            entries = [
                self._to_entry(r).to_dict()
                for r in self.conn.execute("SELECT * FROM entries ORDER BY id ASC").fetchall()
            ]
        return {
            "version": 1,
            "exported_at": _now().isoformat(timespec="seconds"),
            "entries": entries,
            "reviews": [rv.to_dict() for rv in self.list_reviews(limit=100000)],
            "persona_facts": [f.to_dict() for f in self.list_facts(active_only=False)],
        }
