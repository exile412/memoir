"""邮箱账号：注册 / 登录 / 个人资料。

和 auth.py 的区别：
- auth.py 是「整站访问密码」，防的是局域网里别人打开
- 这里管的是「你是谁」，用于个人主页和以后的多用户

不做邮箱验证——本地单机应用没有 SMTP 服务，发不出验证邮件。
邮箱在这里只是账号标识，不证明归属。
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from typing import Any

ITER = 200_000
USER_COOKIE = "memoir_user"
USER_DAYS = 90


def _hash(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), ITER).hex()


class UserStore:
    def __init__(self, store: Any, secret: str) -> None:
        self.store = store
        self.secret = secret
        self._ensure_table()

    def _ensure_table(self) -> None:
        with self.store._lock:
            self.store.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    email         TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    salt          TEXT NOT NULL,
                    nickname      TEXT NOT NULL DEFAULT '',
                    avatar        TEXT NOT NULL DEFAULT '',
                    bio           TEXT NOT NULL DEFAULT '',
                    created_at    TEXT NOT NULL,
                    last_login    TEXT
                );
                """
            )
            self.store.conn.commit()

    # ---------- 账号 ----------
    def register(self, email: str, password: str, nickname: str = "") -> dict[str, Any]:
        email = email.strip().lower()
        if "@" not in email or "." not in email.split("@")[-1]:
            raise ValueError("邮箱格式不对")
        if len(password) < 6:
            raise ValueError("密码至少 6 位")
        salt = secrets.token_hex(16)
        with self.store._lock:
            exists = self.store.conn.execute(
                "SELECT id FROM users WHERE email = ?", (email,)
            ).fetchone()
            if exists:
                raise ValueError("这个邮箱已经注册过了")
            cur = self.store.conn.execute(
                "INSERT INTO users(email, password_hash, salt, nickname, created_at)"
                " VALUES (?,?,?,?,?)",
                (email, _hash(password, salt), salt, nickname.strip() or email.split("@")[0],
                 time.strftime("%Y-%m-%dT%H:%M:%S")),
            )
            self.store.conn.commit()
            return self.get(int(cur.lastrowid))

    def login(self, email: str, password: str) -> dict[str, Any]:
        email = email.strip().lower()
        with self.store._lock:
            row = self.store.conn.execute(
                "SELECT * FROM users WHERE email = ?", (email,)
            ).fetchone()
        if not row:
            raise ValueError("邮箱或密码不对")
        if not hmac.compare_digest(_hash(password, row["salt"]), row["password_hash"]):
            raise ValueError("邮箱或密码不对")
        with self.store._lock:
            self.store.conn.execute(
                "UPDATE users SET last_login = ? WHERE id = ?",
                (time.strftime("%Y-%m-%dT%H:%M:%S"), row["id"]),
            )
            self.store.conn.commit()
        return self.get(int(row["id"]))

    def get(self, user_id: int) -> dict[str, Any]:
        with self.store._lock:
            row = self.store.conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            raise ValueError("用户不存在")
        return {
            "id": row["id"],
            "email": row["email"],
            "nickname": row["nickname"] or row["email"].split("@")[0],
            "avatar": row["avatar"] or "",
            "bio": row["bio"] or "",
            "createdAt": row["created_at"],
            "lastLogin": row["last_login"] or "",
        }

    def update(self, user_id: int, nickname: str | None = None,
               avatar: str | None = None, bio: str | None = None) -> dict[str, Any]:
        sets, params = [], []
        if nickname is not None:
            sets.append("nickname = ?")
            params.append(nickname.strip()[:24])
        if avatar is not None:
            sets.append("avatar = ?")
            params.append(avatar.strip()[:200])
        if bio is not None:
            sets.append("bio = ?")
            params.append(bio.strip()[:120])
        if sets:
            params.append(user_id)
            with self.store._lock:
                self.store.conn.execute(
                    f"UPDATE users SET {', '.join(sets)} WHERE id = ?", params
                )
                self.store.conn.commit()
        return self.get(user_id)

    def count(self) -> int:
        with self.store._lock:
            return int(self.store.conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"])

    # ---------- 会话令牌 ----------
    def make_token(self, user_id: int) -> str:
        exp = int(time.time()) + USER_DAYS * 86400
        payload = f"{user_id}:{exp}"
        sig = hmac.new(self.secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        return payload + ":" + sig

    def check_token(self, token: str) -> int | None:
        try:
            uid_s, exp_s, sig = token.split(":")
            uid, exp = int(uid_s), int(exp_s)
        except (ValueError, AttributeError):
            return None
        if exp < time.time():
            return None
        payload = f"{uid}:{exp}"
        want = hmac.new(self.secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        return uid if hmac.compare_digest(sig, want) else None
