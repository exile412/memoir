# 插件开发

## 它是什么

一个插件就是 `$MEMOIR_HOME/plugins/` 下的一个 `.py` 文件。不用注册、不用打包、不用改主程序。

```bash
ls ~/.memoir/plugins/
# example_mood.py
```

下次运行 `memoir` 时自动加载，`memoir plugins` 可以确认加载状态。

## 三个钩子

全部可选，定义几个都行：

```python
def on_startup(ctx):
    """插件加载时调用一次。"""

def on_entry_added(ctx, entry):
    """每写入一条记忆后调用。entry 是 memoir.models.Entry。"""

def on_review_ready(ctx, review):
    """每生成一份复盘后调用。review 是 memoir.models.Review。"""
```

签名固定，参数位置不能调整。第一个参数永远是 `ctx`。

## ctx 里有什么

| 属性 | 类型 | 说明 |
|---|---|---|
| `ctx.config` | `Config` | 配置对象，含 `model`、`home`、`lang` |
| `ctx.store` | `Store` | 存储层，可读写数据库 |
| `ctx.i18n` | `I18N` | 当前语言，`ctx.i18n.t("cli.add_ok")` |
| `ctx.log(msg)` | 函数 | 写日志到 `~/.memoir/memoir.log` |

## 最小示例

```python
__version__ = "1.0.0"

POSITIVE = ("开心", "顺利", "搞定")
NEGATIVE = ("烦", "累", "崩")

def _score(text: str) -> int:
    t = text.lower()
    return sum(w in t for w in POSITIVE) - sum(w in t for w in NEGATIVE)

def on_startup(ctx):
    ctx.log("mood 插件已加载")

def on_entry_added(ctx, entry):
    if entry.mood is not None:
        return
    score = _score(entry.text)
    if score:
        ctx.log(f"#{entry.id} 初步情绪分 {score:+d}")
```

存成 `~/.memoir/plugins/mood.py`，下次运行就生效。

## 能做什么

- 查数据：`ctx.store.recent(10)`、`ctx.store.search("关键词")`、`ctx.store.entries_for_day(day)`
- 写派生数据：用 `ctx.store` 的方法，别自己开数据库连接
- 自己调模型：`from memoir.llm import LLMClient`，用 `ctx.config.model` 构造
- 读自定义配置：`ctx.config.extra.get("my_key")`

## 不能做什么

- **不能改数据库结构**。要存新字段就用 `entry.meta`（JSON）。
- **不能阻塞太久**。钩子是同步的，慢插件会拖慢每次 `add`。
- **不能互相依赖**。插件按文件名字母序加载，别假设顺序。
- **不能吞异常装作没事**。抛出来，主程序会捕获并记日志，不会崩。

## 调试

```bash
memoir plugins                 # 是否加载成功、暴露了哪些钩子
tail -20 ~/.memoir/memoir.log  # ctx.log 输出与异常堆栈
```

加载失败会在 `memoir plugins` 里显示 `ERR` 和原因，主程序照常工作。

## 分发

单文件就能给，也可以做成目录：

```
my-plugin/
├── my_plugin.py
└── README.md
```

安装 = 把那个 .py 拷进 `~/.memoir/plugins/`。
