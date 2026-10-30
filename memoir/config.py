"""配置加载。

优先级：环境变量 > $MEMOIR_HOME/config.json > 内置默认值。
所有配置本地落盘，不联网、不上报。
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

LANG_CHOICES = ("zh", "en", "ja", "ko")
DEFAULT_REVIEW_AT = "23:30"


def restrict_permissions(path: Path) -> None:
    """把含密钥的文件收紧到仅本人可读写。失败不致命。"""
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def default_home() -> Path:
    env = os.environ.get("MEMOIR_HOME")
    if env:
        return Path(env).expanduser().resolve()
    return (Path.home() / ".memoir").resolve()


@dataclass
class ModelConfig:
    """OpenAI 兼容接口参数。base_url 指向 /v1 结尾即可。"""

    base_url: str = "http://127.0.0.1:11434/v1"
    api_key: str = ""
    name: str = "qwen2.5:7b"
    temperature: float = 0.7
    max_tokens: int = 2048
    timeout: int = 120

    @property
    def is_configured(self) -> bool:
        return bool(self.base_url and self.name)


@dataclass
class Config:
    home: Path = field(default_factory=default_home)
    lang: str = "zh"
    model: ModelConfig = field(default_factory=ModelConfig)
    review_at: str = DEFAULT_REVIEW_AT
    auto_review: bool = True
    plugins_enabled: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    # ---------- 路径 ----------
    @property
    def config_path(self) -> Path:
        return self.home / "config.json"

    @property
    def db_path(self) -> Path:
        return self.home / "memoir.db"

    @property
    def log_path(self) -> Path:
        return self.home / "memoir.log"

    @property
    def plugin_dir(self) -> Path:
        return self.home / "plugins"

    # ---------- 读写 ----------
    def ensure_dirs(self) -> None:
        self.home.mkdir(parents=True, exist_ok=True)
        self.plugin_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def load(cls) -> "Config":
        home = default_home()
        cfg = cls(home=home)
        cfg.ensure_dirs()

        raw: dict[str, Any] = {}
        if cfg.config_path.exists():
            try:
                raw = json.loads(cfg.config_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise ValueError(f"配置文件不是合法 JSON: {cfg.config_path} ({exc})") from exc

        if "lang" in raw:
            cfg.lang = str(raw["lang"])
        if "review_at" in raw:
            cfg.review_at = str(raw["review_at"])
        if "auto_review" in raw:
            cfg.auto_review = bool(raw["auto_review"])
        if isinstance(raw.get("plugins_enabled"), list):
            cfg.plugins_enabled = [str(x) for x in raw["plugins_enabled"]]
        if isinstance(raw.get("model"), dict):
            for k, v in raw["model"].items():
                if hasattr(cfg.model, k):
                    setattr(cfg.model, k, v)
        for k, v in raw.items():
            if k not in {"lang", "review_at", "auto_review", "plugins_enabled", "model"}:
                cfg.extra[k] = v

        env = os.environ
        cfg.lang = env.get("MEMOIR_LANG", cfg.lang)
        cfg.model.base_url = env.get("MEMOIR_BASE_URL", cfg.model.base_url)
        cfg.model.api_key = env.get("MEMOIR_API_KEY", cfg.model.api_key)
        cfg.model.name = env.get("MEMOIR_MODEL", env.get("MEMOIR_MODEL_NAME", cfg.model.name))
        cfg.review_at = env.get("MEMOIR_REVIEW_AT", cfg.review_at)
        if env.get("MEMOIR_TEMPERATURE"):
            cfg.model.temperature = float(env["MEMOIR_TEMPERATURE"])
        if env.get("MEMOIR_MAX_TOKENS"):
            cfg.model.max_tokens = int(env["MEMOIR_MAX_TOKENS"])
        if env.get("MEMOIR_TIMEOUT"):
            cfg.model.timeout = int(env["MEMOIR_TIMEOUT"])

        if cfg.lang not in LANG_CHOICES:
            cfg.lang = "zh"
        return cfg

    def save(self) -> Path:
        """把配置写入 config.json。

        注意：文件里含 api_key 明文，落盘后立刻收紧权限（POSIX 上 600）。
        Windows 的 chmod 只能控制只读位，真正的隔离靠用户目录 ACL。
        """
        self.ensure_dirs()
        payload = {
            "lang": self.lang,
            "review_at": self.review_at,
            "auto_review": self.auto_review,
            "plugins_enabled": self.plugins_enabled,
            "model": asdict(self.model),
        }
        payload.update(self.extra)
        self.config_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        restrict_permissions(self.config_path)
        return self.config_path
