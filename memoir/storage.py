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
    user_id INTEGER NOT NULL DEFAULT 0,
    author  TEXT NOT NULL DEFAULT 'me',
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
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS folders (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                name       TEXT NOT NULL,
                parent_id  INTEGER,
                sort       INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
            """
        )
        # 老库迁移：补 user_id 列（0 = 未登录时的本地账本）
        try:
            self.conn.execute(
                "ALTER TABLE entries ADD COLUMN user_id INTEGER NOT NULL DEFAULT 0"
            )
        except sqlite3.OperationalError:
            pass
        try:
            self.conn.execute(
                "ALTER TABLE entries ADD COLUMN author TEXT NOT NULL DEFAULT 'me'"
            )
        except sqlite3.OperationalError:
            pass
        try:
            self.conn.execute("ALTER TABLE entries ADD COLUMN folder_id INTEGER")
        except sqlite3.OperationalError:
            pass
        # 已经不做多用户了：把历史上归属某个账号的记录归零，否则界面上看不见
        try:
            self.conn.execute("UPDATE entries SET user_id = 0 WHERE user_id != 0")
        except sqlite3.OperationalError:
            pass
        self.conn.commit()
        restrict_permissions(self.path)
        self.current_user_id = 0

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
        author: str = "me",
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
            getattr(self, "current_user_id", 0),
            author,
        )
        with self._lock:
            cur = self.conn.execute(
                "INSERT INTO entries(ts, day, kind, text, tags, mood, source, meta, user_id, author)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
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
        sql = "SELECT * FROM entries WHERE day = ? AND user_id = ?"
        params: list[Any] = [day, getattr(self, "current_user_id", 0)]
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
                "SELECT * FROM entries WHERE day >= ? AND day <= ? AND user_id = ?"
                " ORDER BY ts ASC, id ASC",
                (start_day, end_day, getattr(self, "current_user_id", 0)),
            ).fetchall()
        return [self._to_entry(r) for r in rows]

    def recent(self, limit: int = 20) -> list[Entry]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM entries WHERE user_id = ? ORDER BY ts DESC, id DESC LIMIT ?",
                (getattr(self, "current_user_id", 0), limit)
            ).fetchall()
        return [self._to_entry(r) for r in rows]

    def days_with_entries(self, limit: int = 30) -> list[str]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT day, COUNT(*) c FROM entries WHERE user_id = ?"
                " GROUP BY day ORDER BY day DESC LIMIT ?",
                (getattr(self, "current_user_id", 0), limit),
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

    def update_entry(self, entry_id: int, text: str | None = None,
                     kind: str | None = None, tags: str | None = None) -> bool:
        """按需更新字段。FTS 由触发器同步。"""
        sets: list[str] = []
        params: list[Any] = []
        if text is not None:
            sets.append("text = ?")
            params.append(text)
        if kind is not None:
            sets.append("kind = ?")
            params.append(kind)
        if tags is not None:
            sets.append("tags = ?")
            params.append(tags)
        if not sets:
            return False
        params.append(entry_id)
        with self._lock:
            cur = self.conn.execute(
                f"UPDATE entries SET {', '.join(sets)} WHERE id = ?", params
            )
            self.conn.commit()
            return cur.rowcount > 0

    def delete_entry(self, entry_id: int) -> bool:
        with self._lock:
            cur = self.conn.execute("DELETE FROM entries WHERE id = ?", (entry_id,))
            self.conn.commit()
            return cur.rowcount > 0

    def list_groups(self, limit: int = 40) -> list[str]:
        """把条目 tags 拆成去重分组，供前端选择。"""
        import re as _re

        with self._lock:
            rows = self.conn.execute(
                "SELECT tags FROM entries WHERE tags != '' ORDER BY id DESC LIMIT 2000"
            ).fetchall()
        seen: list[str] = []
        for r in rows:
            for g in _re.split(r"[,，\s]+", r["tags"] or ""):
                g = g.strip()
                if g and g not in seen:
                    seen.append(g)
            if len(seen) >= limit:
                break
        return seen

    def by_author(self) -> dict[str, int]:
        """按作者统计条数，给侧栏分组用。"""
        with self._lock:
            rows = self.conn.execute(
                "SELECT author, COUNT(*) c FROM entries WHERE user_id = ? GROUP BY author",
                (getattr(self, "current_user_id", 0),),
            ).fetchall()
        out = {"me": 0, "ai": 0}
        for r in rows:
            out[r["author"]] = int(r["c"])
        return out

    def recent_by(self, author: str, limit: int = 60) -> list[Any]:
        """只取某个作者写的。"""
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM entries WHERE user_id = ? AND author = ?"
                " ORDER BY ts DESC, id DESC LIMIT ?",
                (getattr(self, "current_user_id", 0), author, limit),
            ).fetchall()
        return [self._to_entry(r) for r in rows]

    # ---------- 文件夹 ----------
    def folder_tree(self) -> list[dict[str, Any]]:
        """返回整棵树（含每个文件夹的直接条目数）。"""
        uid = getattr(self, "current_user_id", 0)
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM folders ORDER BY sort ASC, id ASC"
            ).fetchall()
            counts = {
                r["folder_id"]: int(r["c"])
                for r in self.conn.execute(
                    "SELECT folder_id, COUNT(*) c FROM entries"
                    " WHERE user_id = ? AND folder_id IS NOT NULL GROUP BY folder_id",
                    (uid,),
                ).fetchall()
            }
        nodes = {
            r["id"]: {
                "id": r["id"], "name": r["name"], "parentId": r["parent_id"],
                "sort": r["sort"], "count": counts.get(r["id"], 0), "children": [],
            }
            for r in rows
        }
        roots: list[dict[str, Any]] = []
        for n in nodes.values():
            parent = nodes.get(n["parentId"]) if n["parentId"] else None
            if parent is None:
                roots.append(n)
            else:
                parent["children"].append(n)
        return roots

    def folder_add(self, name: str, parent_id: int | None = None) -> int:
        name = (name or "").strip()[:40]
        if not name:
            raise ValueError("名字不能为空")
        with self._lock:
            row = self.conn.execute(
                "SELECT COALESCE(MAX(sort), -1) + 1 s FROM folders WHERE parent_id IS ?",
                (parent_id,),
            ).fetchone()
            cur = self.conn.execute(
                "INSERT INTO folders(name, parent_id, sort, created_at) VALUES (?,?,?,?)",
                (name, parent_id, int(row["s"]), _now().isoformat(timespec="seconds")),
            )
            self.conn.commit()
            return int(cur.lastrowid)

    def folder_rename(self, folder_id: int, name: str) -> None:
        name = (name or "").strip()[:40]
        if not name:
            raise ValueError("名字不能为空")
        with self._lock:
            self.conn.execute("UPDATE folders SET name = ? WHERE id = ?", (name, folder_id))
            self.conn.commit()

    def folder_delete(self, folder_id: int) -> int:
        """删文件夹：子文件夹一起删，里面的条目回到根。"""
        killed: list[int] = []
        with self._lock:
            stack = [folder_id]
            while stack:
                cur = stack.pop()
                killed.append(cur)
                stack.extend(
                    r["id"]
                    for r in self.conn.execute(
                        "SELECT id FROM folders WHERE parent_id = ?", (cur,)
                    ).fetchall()
                )
            marks = ",".join("?" * len(killed))
            self.conn.execute(
                f"UPDATE entries SET folder_id = NULL WHERE folder_id IN ({marks})", killed
            )
            self.conn.execute(f"DELETE FROM folders WHERE id IN ({marks})", killed)
            self.conn.commit()
        return len(killed)

    def folder_move(self, folder_id: int, parent_id: int | None, sort: int) -> None:
        """挪动文件夹：防成环（不能挪进自己的子孙里）。"""
        with self._lock:
            if parent_id is not None:
                # 从被移动的节点往下找，撞见目标父节点就是成环
                stack = [folder_id]
                seen = set()
                while stack:
                    cur = stack.pop()
                    if cur == parent_id:
                        raise ValueError("不能把文件夹移进它自己里面")
                    if cur in seen:
                        continue
                    seen.add(cur)
                    stack.extend(
                        r["id"]
                        for r in self.conn.execute(
                            "SELECT id FROM folders WHERE parent_id = ?", (cur,)
                        ).fetchall()
                    )
            self.conn.execute(
                "UPDATE folders SET parent_id = ?, sort = ? WHERE id = ?",
                (parent_id, sort, folder_id),
            )
            self.conn.commit()

    def entry_move(self, entry_id: int, folder_id: int | None) -> None:
        with self._lock:
            self.conn.execute(
                "UPDATE entries SET folder_id = ? WHERE id = ?", (folder_id, entry_id)
            )
            self.conn.commit()

    def entries_in_folder(self, folder_id: int | None, limit: int = 200) -> list[Entry]:
        uid = getattr(self, "current_user_id", 0)
        with self._lock:
            if folder_id is None:
                rows = self.conn.execute(
                    "SELECT * FROM entries WHERE user_id = ? AND folder_id IS NULL"
                    " ORDER BY ts DESC, id DESC LIMIT ?",
                    (uid, limit),
                ).fetchall()
            else:
                rows = self.conn.execute(
                    "SELECT * FROM entries WHERE user_id = ? AND folder_id = ?"
                    " ORDER BY ts DESC, id DESC LIMIT ?",
                    (uid, folder_id, limit),
                ).fetchall()
        return [self._to_entry(r) for r in rows]

    def ensure_default_folders(self) -> None:
        """首次启动给几个分类，省得面对空树。"""
        with self._lock:
            n = int(self.conn.execute("SELECT COUNT(*) c FROM folders").fetchone()["c"])
        if n:
            return
        for name in ("日常记录", "心里话", "性格笔记", "模型配置"):
            self.folder_add(name)

    def insights(self, days: int = 30) -> dict[str, Any]:
        """给界面画图用的统计：近 N 天记录数、情绪均值、时段分布、类型分布、连续天数。"""
        from datetime import date as _date
        from datetime import timedelta

        uid = getattr(self, "current_user_id", 0)
        today = _date.today()
        since = (today - timedelta(days=days - 1)).isoformat()

        with self._lock:
            rows = self.conn.execute(
                "SELECT day, COUNT(*) n, AVG(mood) m FROM entries"
                " WHERE day >= ? AND user_id = ? GROUP BY day ORDER BY day",
                (since, uid),
            ).fetchall()
            by_day = {r["day"]: {"n": int(r["n"]), "mood": r["m"]} for r in rows}

            kinds = self.conn.execute(
                "SELECT kind, COUNT(*) c FROM entries WHERE user_id = ? GROUP BY kind"
                " ORDER BY c DESC",
                (uid,),
            ).fetchall()

            hours = self.conn.execute(
                "SELECT substr(ts, 12, 2) h, COUNT(*) c FROM entries WHERE user_id = ?"
                " GROUP BY h ORDER BY h",
                (uid,),
            ).fetchall()

            days_rows = [
                r["day"]
                for r in self.conn.execute(
                    "SELECT DISTINCT day FROM entries WHERE user_id = ? ORDER BY day DESC",
                    (uid,),
                ).fetchall()
            ]

        series = []
        for i in range(days):
            d = (today - timedelta(days=days - 1 - i)).isoformat()
            item = by_day.get(d)
            series.append({"day": d, "count": item["n"] if item else 0,
                           "mood": round(item["mood"], 2) if item and item["mood"] is not None else None})

        streak = 0
        cursor = today
        have = {d for d in days_rows}
        while cursor.isoformat() in have:
            streak += 1
            cursor -= timedelta(days=1)

        return {
            "days": days,
            "series": series,
            "streak": streak,
            "total": sum(v["n"] for v in by_day.values()),
            "kinds": [{"kind": r["kind"], "count": int(r["c"])} for r in kinds],
            "hours": [{"hour": r["h"], "count": int(r["c"])} for r in hours],
        }

    def claim_anonymous(self, user_id: int) -> int:
        """把未登录时记下的条目并入某个账号（注册时调用，幂等）。"""
        with self._lock:
            cur = self.conn.execute(
                "UPDATE entries SET user_id = ? WHERE user_id = 0", (user_id,)
            )
            self.conn.commit()
            return cur.rowcount

    def count_entries(self) -> int:
        with self._lock:
            return int(
                self.conn.execute(
                    "SELECT COUNT(*) c FROM entries WHERE user_id = ?",
                    (getattr(self, "current_user_id", 0),),
                ).fetchone()["c"]
            )

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
