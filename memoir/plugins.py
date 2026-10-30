"""插件系统。

一个插件就是一个 .py 文件，放在 $MEMOIR_HOME/plugins/ 下，定义至少一个模块级
钩子函数（见 docs/plugins.md）：

    on_startup(ctx)                 # 加载时
    on_entry_added(ctx, entry)      # 每写入一条记忆
    on_review_ready(ctx, review)    # 每生成一份复盘

插件拿到的 ctx 里有 config / store / i18n / log，可以读写数据库、调模型。
插件失败不会影响主流程，异常会被捕获并记日志。
"""

from __future__ import annotations

import importlib.util
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

HOOKS = ("on_startup", "on_entry_added", "on_review_ready")


@dataclass
class PluginContext:
    config: Any
    store: Any
    i18n: Any
    logger: Callable[[str], None]

    def log(self, message: str) -> None:
        self.logger(message)


class PluginManager:
    def __init__(self, ctx: PluginContext, plugin_dir: Path | None = None) -> None:
        self.ctx = ctx
        self.plugin_dir = plugin_dir or ctx.config.plugin_dir
        self.plugins: dict[str, Any] = {}
        self.errors: dict[str, str] = {}

    # ---------- 加载 ----------
    def discover(self) -> list[Path]:
        if not self.plugin_dir.exists():
            return []
        return sorted(p for p in self.plugin_dir.glob("*.py") if not p.name.startswith("_"))

    def load_all(self) -> dict[str, Any]:
        """加载插件。config.plugins_enabled 非空时，只加载名单里的。"""
        allowed = {n.strip() for n in (self.ctx.config.plugins_enabled or []) if n.strip()}
        for path in self.discover():
            if allowed and path.stem not in allowed:
                self.ctx.log(f"[plugin:{path.stem}] 不在 plugins_enabled 名单内，跳过")
                continue
            self.load_file(path)
        return self.plugins

    def load_file(self, path: Path) -> Any | None:
        name = path.stem
        try:
            spec = importlib.util.spec_from_file_location(f"memoir_plugin_{name}", path)
            if spec is None or spec.loader is None:
                raise ImportError("无法创建模块 spec")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            if not any(hasattr(module, h) for h in HOOKS):
                raise ImportError("没有定义任何钩子函数（on_startup / on_entry_added / on_review_ready）")
            self.plugins[name] = module
            self.errors.pop(name, None)
            self._fire_one(module, "on_startup", self.ctx)
            return module
        except Exception as exc:  # 插件隔离：坏插件不能拖垮主流程
            self.errors[name] = f"{type(exc).__name__}: {exc}"
            self.ctx.log(f"[plugin:{name}] 加载失败: {exc}")
            return None

    # ---------- 触发 ----------
    def _fire_one(self, module: Any, hook: str, *args: Any) -> None:
        fn = getattr(module, hook, None)
        if not callable(fn):
            return
        try:
            fn(*args)
        except Exception as exc:
            name = getattr(module, "__name__", "?")
            self.ctx.log(f"[plugin:{name}] {hook} 异常: {exc}\n{traceback.format_exc(limit=3)}")

    def fire(self, hook: str, *args: Any) -> None:
        """统一把 ctx 作为第一个参数传进去，和 on_startup 的签名保持一致。"""
        for module in self.plugins.values():
            self._fire_one(module, hook, self.ctx, *args)

    # ---------- 信息 ----------
    def describe(self) -> list[dict[str, Any]]:
        rows = []
        for name, mod in self.plugins.items():
            hooks = [h for h in HOOKS if callable(getattr(mod, h, None))]
            rows.append(
                {
                    "name": name,
                    "version": getattr(mod, "__version__", "-"),
                    "description": getattr(mod, "__doc__", "") or "",
                    "hooks": hooks,
                    "status": "ok",
                }
            )
        for name, err in self.errors.items():
            rows.append({"name": name, "version": "-", "description": err, "hooks": [], "status": "error"})
        return rows
