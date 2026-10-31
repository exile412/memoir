"""单密码门禁。

没有账号体系——整个站点一个密码，登录一次记 30 天。
密码用 PBKDF2 存哈希，登录凭证是 HMAC 签名的过期时间戳（无状态，重启不掉线）。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from pathlib import Path

TOKEN_DAYS = 30
COOKIE_NAME = "memoir_token"
_ITER = 200_000


class Auth:
    def __init__(self, home: Path) -> None:
        self.path = Path(home) / "auth.json"
        self.data: dict = {}
        self._load()

    # ---------- 存储 ----------
    def _load(self) -> None:
        try:
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self.data = {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            import os

            os.chmod(self.path, 0o600)
        except OSError:
            pass

    # ---------- 密码 ----------
    @property
    def enabled(self) -> bool:
        return bool(self.data.get("hash"))

    def set_password(self, password: str) -> None:
        salt = secrets.token_hex(16)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), _ITER).hex()
        self.data = {
            "salt": salt,
            "hash": digest,
            "secret": secrets.token_hex(32),
            "created": int(time.time()),
        }
        self._save()

    def check(self, password: str) -> bool:
        if not self.enabled:
            return False
        salt = bytes.fromhex(self.data["salt"])
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _ITER).hex()
        return hmac.compare_digest(digest, self.data["hash"])

    def clear(self) -> None:
        self.data = {}
        self._save()

    # ---------- 令牌 ----------
    def make_token(self) -> str:
        exp = int(time.time()) + TOKEN_DAYS * 86400
        payload = str(exp)
        sig = hmac.new(self.data["secret"].encode(), payload.encode(), hashlib.sha256).hexdigest()
        return payload + "." + sig

    def valid(self, token: str) -> bool:
        if not token or not self.enabled:
            return False
        try:
            payload, sig = token.split(".", 1)
            exp = int(payload)
        except (ValueError, AttributeError):
            return False
        if exp < time.time():
            return False
        want = hmac.new(self.data["secret"].encode(), payload.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(sig, want)
