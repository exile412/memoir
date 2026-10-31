"""memoir — 本地私有化个人 AI 记忆系统。

模块划分：
    storage   记忆存储（SQLite + FTS5）
    llm       模型接入（OpenAI 兼容，零第三方依赖）
    review    夜间复盘
    persona   人格档案
    plugins   插件系统
    cli       命令行入口
"""

__version__ = "0.5.0"
__all__ = ["__version__"]
