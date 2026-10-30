# memoir · 记忆

> 白天记下来，夜里还给你。一个完全跑在你自己电脑上的个人 AI 记忆系统。

`memoir` 记录你每天做的事、想的事、心情的起伏；每天晚上自动把这些流水账还原成一份**你认得出来的**复盘；日子久了，它攒出一份关于"你是个什么样的人"的档案。

不是笔记软件，不是聊天机器人，不是某个平台的插件。**一个独立的 Python 程序**，数据全在一个 SQLite 文件里，模型接本地的也行。

```
$ memoir add "上午改插件的注册方式，还是没生效，有点烦" --kind event --tags 编程
已记下 #1（event）

$ memoir add "其实我有点怀疑自己是不是不适合折腾这些，但又不甘心" --kind thought
已记下 #2（thought）

$ memoir review
2026-10-30 · 今日复盘
=================

【今天做了什么】
上午改插件的注册方式，一直没生效；晚上跟家里通了电话，情绪缓下来了。

【心里话与情绪】
"是不是不适合折腾这些，但又不甘心"——不是想放弃，是累了又不认。
烦的点不在技术，在"又白花了时间"。

【想法与思维变化】
从"一定要弄成"滑到"算了别弄了"，中间没有停下来评估成本，是被反复失败推着走的。

【性格与状态】
对认定的事有股不服气，但容易被连续的挫败拖垮。今天的精力是往下走的。

【给你的话】
你不是不够聪明，是连着失败了五次还在硬扛。
明天先花十分钟确认最小可行的那一步，再决定要不要继续。
今晚早点睡。

—— 依据 2 条记录 · 模型 qwen3-8b · 语言 zh
```

（上面是真实运行的输出，模型是本机 Ollama 跑的 8B 模型。）

---

## 目录

- [它做什么](#它做什么)
- [快速开始](#快速开始)
- [每晚自动复盘](#每晚自动复盘)
- [人格档案](#人格档案)
- [模型接入](#模型接入)
- [插件](#插件)
- [多语言](#多语言)
- [隐私](#隐私)
- [命令一览](#命令一览)
- [项目结构](#项目结构)
- [常见问题](#常见问题)

## 它做什么

| # | 能力 | 怎么做的 |
|---|---|---|
| 1 | **全天候记录** | `memoir add` 随手记，带类型（事件/想法/情绪/备注）、标签、情绪分；也可以管道喂、插件自动采 |
| 2 | **每晚自动复盘** | 到点自动把当天所有记录还原成五段：做了什么 / 心里话 / 思维变化 / 性格状态 / 给你的话 |
| 3 | **长期人格档案** | 每次复盘后蒸馏出"有证据的观察"，累积成画像；越用越准 |
| 4 | **背靠任意模型** | 任何 OpenAI 兼容接口：Ollama、vLLM、LM Studio、llama.cpp、DeepSeek、Qwen…换模型只改三个环境变量 |
| 5 | **插件扩展** | `~/.memoir/plugins/*.py` 丢进去就生效，不需要改主程序 |
| 6 | **多国语言** | 中/英/日/韩；换语言 = 换提示词 = 换一个母语者在跟你说话 |
| 7 | **完全本地** | 无服务器、无账号、无遥测；一个 .db 文件就是全部 |

### 它不是什么

- ❌ 不是网页套壳，没有 Web 界面，也没有云
- ❌ 不是某个平台的插件/扩展
- ❌ 不做日程管理、待办、笔记同步——只做「记忆 → 复盘 → 人格」

### 没有模型也能用

模型挂了不会让程序崩。复盘会降级成本地统计摘要，标注 `model=fallback`，并且**不会**把降级内容写进人格档案。

## 快速开始

需要 Python **3.10+**，没有第三方依赖。

```bash
git clone https://github.com/<you>/memoir.git
cd memoir
pip install -e .
```

或者不装，直接在仓库里跑：

```bash
python -m memoir --help
```

记第一条：

```bash
memoir add "今天把那个卡了三天的 bug 修了" --kind event --mood 2
memoir add "修完其实没想象中爽，就是松了口气" --kind feeling
memoir today
```

看一眼复盘（还没配模型，先看本地摘要）：

```bash
memoir review --offline
```

接上本机 Ollama，让复盘有内容：

```bash
ollama pull qwen2.5:7b
export MEMOIR_BASE_URL=http://127.0.0.1:11434/v1
export MEMOIR_MODEL=qwen2.5:7b
memoir model      # 探活
memoir review     # 真正的复盘
```

配好后每天跑一次：

```bash
memoir once       # 手动跑一次夜间任务（复盘 + 人格蒸馏）
memoir daemon     # 常驻，每天 23:30 自动跑
```

## 每晚自动复盘

`memoir daemon` 会一直挂着，到点干活。但更省心的做法是交给系统定时器。

### Windows（任务计划程序）

```powershell
schtasks /create /tn "memoir nightly" /sc daily /st 23:30 ^
  /tr "python -m memoir once"
```

### macOS / Linux（cron）

```bash
crontab -e
# 每天 23:30
30 23 * * * cd /path/to/memoir && /usr/bin/python3 -m memoir once >> ~/.memoir/cron.log 2>&1
```

### Linux（systemd，推荐常驻）

```ini
# ~/.config/systemd/user/memoir.service
[Unit]
Description=memoir nightly review

[Service]
ExecStart=/usr/bin/python3 -m memoir daemon
WorkingDirectory=%h/memoir
Environment=MEMOIR_BASE_URL=http://127.0.0.1:11434/v1
Environment=MEMOIR_MODEL=qwen2.5:7b
Restart=always

[Install]
WantedBy=default.target
```

```bash
systemctl --user enable --now memoir
```

第二天早上 `memoir review --date 2026-10-30` 就能看到前一晚的结果。

## 人格档案

```bash
memoir persona               # 看现在攒出了什么
memoir persona --distill     # 手动触发一次蒸馏（默认每天复盘后自动做）
```

输出长这样：

```
我眼里的你
=========

## 性格
- 对认定的事有股不服气，连续挫败后仍会再试  · 置信度 0.72（2026-10-28）

## 软肋
- 容易把"技术没弄成"读成"我不行"  · 置信度 0.61（2026-10-30: "是不是不适合折腾这些"）

## 成长
- 开始有意识地区分"累"和"不想做"  · 置信度 0.55（2026-10-30）

累计 42 条记录 / 9 天 / 8 份复盘
```

每条都带**证据**和**置信度**。没有证据的观察不会进档案，降级的本地摘要也不会。

## 模型接入

任何 OpenAI 格式的 `/v1/chat/completions` 都能接：

```bash
export MEMOIR_BASE_URL=http://127.0.0.1:11434/v1   # Ollama
export MEMOIR_MODEL=qwen2.5:7b
export MEMOIR_API_KEY=                              # 本地留空
```

线上服务同理：

```bash
export MEMOIR_BASE_URL=https://api.deepseek.com/v1
export MEMOIR_MODEL=deepseek-chat
export MEMOIR_API_KEY=sk-xxxx
```

完整的服务清单、调参建议和排错见 [docs/03-models.md](docs/03-models.md)。

## 插件

把 .py 丢进 `~/.memoir/plugins/` 就生效：

```python
def on_entry_added(ctx, entry):
    ctx.log(f"新记录 #{entry.id}: {entry.text[:20]}")
```

三个钩子：`on_startup` / `on_entry_added` / `on_review_ready`。
插件异常会被隔离，不影响主流程。

写法和限制见 [docs/02-plugins.md](docs/02-plugins.md)，示例见 [plugins/example_mood.py](plugins/example_mood.py)。

## 多语言

```bash
memoir lang ja       # 界面 + 提示词 + 复盘输出，全变日文
memoir --lang ko today
```

翻译机制、怎么加新语言见 [docs/04-languages.md](docs/04-languages.md)。

## 隐私

| 问题 | 答案 |
|---|---|
| 数据存在哪 | `~/.memoir/memoir.db`，一个 SQLite 文件 |
| 会上传吗 | 不会。除了你配的模型接口，程序不发起任何网络请求 |
| 有账号吗 | 没有 |
| 有遥测吗 | 没有 |
| 能带走吗 | `memoir export` 出完整 JSON |
| 能彻底删掉吗 | 删掉那个 .db 文件即可 |

用线上模型时，发给模型的是当天的记录文本（和已有档案）。这是使用线上模型的固有代价，不是 memoir 的额外行为。**最私密的用法是本地模型**。

## 命令一览

| 命令 | 作用 |
|---|---|
| `memoir add <text>` | 记一条；`--kind` `--tags` `--mood` |
| `memoir today [--date]` | 看某天的记录 |
| `memoir review [--date] [--offline]` | 生成复盘 |
| `memoir persona [--distill]` | 看/更新人格档案 |
| `memoir search <query>` | 全文检索（中文可搜） |
| `memoir stats` | 统计 |
| `memoir export [-o file]` | 导出全部为 JSON |
| `memoir plugins` | 插件列表与加载状态 |
| `memoir model` | 探活模型 |
| `memoir config [--edit]` | 查看/写配置 |
| `memoir lang <code>` | 切语言 |
| `memoir once [--date]` | 跑一次夜间任务 |
| `memoir daemon` | 常驻，到点自动复盘 |

## 项目结构

```
memoir/
├── memoir/
│   ├── config.py       配置（环境变量 > config.json > 默认）
│   ├── storage.py      SQLite + FTS5
│   ├── llm.py          OpenAI 兼容客户端（零依赖）
│   ├── prompts.py      提示词组装
│   ├── review.py       复盘引擎
│   ├── persona.py      人格档案
│   ├── plugins.py      插件加载与钩子
│   ├── scheduler.py    夜间调度
│   ├── cli.py          命令行
│   └── locales/        zh / en / ja / ko
├── plugins/
│   └── example_mood.py 示例插件
├── docs/
│   ├── 01-architecture.md
│   ├── 02-plugins.md
│   ├── 03-models.md
│   └── 04-languages.md
├── tests/
│   └── test_smoke.py
├── pyproject.toml
├── .env.example
└── LICENSE
```

## 常见问题

**复盘没内容 / 写着「模型不可用」**
模型没连上。`memoir model` 看具体原因，检查 `MEMOIR_BASE_URL` 和模型名。

**模型名字报 404**
名必须和服务里一致。`curl -s $MEMOIR_BASE_URL/models` 查，Ollama 的名字常带 `:latest`。

**复盘内容很空、像模板**
换大一点的模型，或在 `config.json` 里把 `temperature` 调到 0.7 左右。

**同一天想重跑复盘**
直接再跑 `memoir review`，会覆盖当天那份，不会堆重复。

**记录写错了**
目前用 SQL 或重新 `export` 修正。`memoir` 故意不提供批量编辑，避免误删记忆。

**中文搜索搜不到**
FTS 用 trigram，1-2 个字会退回 LIKE；词越长越准。

**换电脑**
整个 `~/.memoir` 目录拷走即可。想只说数据就拷那个 .db。

## 开发

```bash
python tests/test_smoke.py     # 不需要 pytest
python -m pytest tests/ -q     # 装了 pytest 也行
```

9 个测试覆盖：存取、检索、删除、复盘幂等、空日、人格降级、语言包完整性、JSON 抠取容错、导出结构。

## License

[MIT](LICENSE)
