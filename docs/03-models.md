# 模型接入

## 前提

任何实现了 **OpenAI `/v1/chat/completions`** 的服务都能接。memoir 只用标准库发一个 POST，不依赖任何 SDK。

三个参数决定一切：

| 环境变量 | 含义 | 例子 |
|---|---|---|
| `MEMOIR_BASE_URL` | 接口地址，到 `/v1` 为止 | `http://127.0.0.1:11434/v1` |
| `MEMOIR_MODEL` | 模型名，必须和服务里一致 | `qwen2.5:7b` |
| `MEMOIR_API_KEY` | 本地模型留空即可 | `sk-...` |

也可以写进 `~/.memoir/config.json`：

```json
{
  "model": {
    "base_url": "http://127.0.0.1:11434/v1",
    "name": "qwen2.5:7b",
    "api_key": "",
    "temperature": 0.7,
    "max_tokens": 2048,
    "timeout": 120
  }
}
```

环境变量优先于文件。

## 常见服务

### Ollama（最省事）

```bash
ollama serve
ollama pull qwen2.5:7b

export MEMOIR_BASE_URL=http://127.0.0.1:11434/v1
export MEMOIR_MODEL=qwen2.5:7b
memoir model
```

看本机有哪些模型：`curl -s http://127.0.0.1:11434/v1/models`

### vLLM

```bash
vllm serve Qwen/Qwen2.5-7B-Instruct --port 8000
export MEMOIR_BASE_URL=http://127.0.0.1:8000/v1
export MEMOIR_MODEL=Qwen/Qwen2.5-7B-Instruct
```

### LM Studio

界面里开 Local Server（默认 1234）：

```bash
export MEMOIR_BASE_URL=http://127.0.0.1:1234/v1
export MEMOIR_MODEL=<界面上显示的名字>
```

### llama.cpp server

```bash
llama-server -m model.gguf --port 8080
export MEMOIR_BASE_URL=http://127.0.0.1:8080/v1
```

### 线上 OpenAI 兼容服务

DeepSeek / DashScope(Qwen) / Moonshot / Together / Groq / OpenRouter 接法完全一样：

```bash
export MEMOIR_BASE_URL=https://api.deepseek.com/v1
export MEMOIR_MODEL=deepseek-chat
export MEMOIR_API_KEY=sk-xxxx
```

key 只在你自己的环境变量里，memoir 不写库、不上传。

## 调参建议

| 参数 | 建议 | 原因 |
|---|---|---|
| `temperature` | 0.6–0.8 | 太低像公文，太高会编 |
| `max_tokens` | 1024–2048 | 五段式复盘 800 token 足够 |
| `timeout` | 120–300 | 本地 7B 首次加载慢 |

模型越小越要盯"有没有输出 JSON"。解析失败会自动降级，不会写脏数据。

## 排错

**`HTTP 404 model not found`**
模型名不对。`curl -s $MEMOIR_BASE_URL/models` 看真实名字，Ollama 的名字通常带 `:latest`。

**`HTTP 401`**
需要 key 但没给，或 key 无效。本地服务一般不需要 key。

**`无法连接模型服务`**
服务没启动或端口不对。先 `curl -s $MEMOIR_BASE_URL/models`。

**`响应结构不符合 OpenAI 格式`**
这个服务不是 OpenAI 兼容协议。

**超时**
调大 `MEMOIR_TIMEOUT`，首次加载大模型可能一两分钟。

**模型输出的不是 JSON**
不影响使用，自动降级为本地摘要。想提高成功率换更大的模型，或把 `locales/*.json` 里 `prompts.review_system` 写得更严格。

## 探活

```bash
memoir model
```

成功打印模型回的第一句话，失败打印具体原因和地址。
