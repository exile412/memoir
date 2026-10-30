"""多语言：界面文案 + 提示词模板，全部来自 locales/*.json。

回退顺序：目标语言 -> en -> zh -> 键名本身。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

LOCALE_DIR = Path(__file__).parent / "locales"
FALLBACK_ORDER = ("en", "zh")


class I18N:
    def __init__(self, lang: str = "zh", locale_dir: Path | None = None) -> None:
        self.lang = lang
        self.locale_dir = locale_dir or LOCALE_DIR
        self._cache: dict[str, dict[str, Any]] = {}

    def _load(self, lang: str) -> dict[str, Any]:
        if lang in self._cache:
            return self._cache[lang]
        path = self.locale_dir / f"{lang}.json"
        data: dict[str, Any] = {}
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                data = {}
        self._cache[lang] = data
        return data

    def raw(self, key: str) -> Any:
        for lang in (self.lang, *FALLBACK_ORDER):
            if not lang:
                continue
            node: Any = self._load(lang)
            for part in key.split("."):
                if not isinstance(node, dict) or part not in node:
                    node = None
                    break
                node = node[part]
            if node is not None:
                return node
        return None

    def t(self, key: str, **kwargs: Any) -> str:
        value = self.raw(key)
        if value is None:
            return key
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        text = str(value)
        for k, v in kwargs.items():
            text = text.replace("{" + k + "}", str(v))
        return text

    def section(self, key: str) -> dict[str, Any]:
        value = self.raw(key)
        return value if isinstance(value, dict) else {}

    def available(self) -> list[str]:
        return sorted(p.stem for p in self.locale_dir.glob("*.json"))
