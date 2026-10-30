"""示例插件：情绪词打分 + 每日条数统计。

演示三个钩子怎么用，可以直接复制改名做成你自己的插件。

安装：把本文件拷到 ~/.memoir/plugins/ 下，重启 memoir 即可生效。
"""

__version__ = "1.0.0"

POSITIVE = ("开心", "顺利", "搞定", "很好", "喜欢", "进展", "happy", "great", "done", "love")
NEGATIVE = ("烦", "累", "崩", "失败", "卡住", "焦虑", "难受", "angry", "tired", "stuck", "fail")


def _score(text: str) -> int:
    t = text.lower()
    pos = sum(1 for w in POSITIVE if w in t)
    neg = sum(1 for w in NEGATIVE if w in t)
    return pos - neg


def on_startup(ctx):
    ctx.log("[example_mood] 已加载")


def on_entry_added(ctx, entry):
    """给没打过情绪分的事件补一个粗分，写进 entry.meta。"""
    if entry.mood is not None:
        return
    score = _score(entry.text)
    if score:
        ctx.log(f"[example_mood] #{entry.id} 初步情绪分 {score:+d}")


def on_review_ready(ctx, review):
    """复盘生成后，把当天条数追加到日志，方便观察节奏。"""
    ctx.log(f"[example_mood] {review.day} 共 {review.entries_count} 条记录")
