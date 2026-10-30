"""模型接入：任何 OpenAI 兼容的 /chat/completions 接口。

零第三方依赖（只用标准库 urllib），所以离线机器上装好 Python 就能跑。
适配：Ollama、vLLM、LM Studio、llama.cpp server、DeepSeek、Qwen(DashScope)、
Together、Groq、OpenRouter 等一切遵循 OpenAI 格式的服务。
"""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Sequence

from .config import ModelConfig


class LLMError(RuntimeError):
    """模型调用失败（连接、鉴权、响应格式）。"""


@dataclass
class ChatResult:
    text: str
    model: str = ""
    tokens: int = 0


Message = dict[str, str]


class LLMClient:
    def __init__(self, cfg: ModelConfig) -> None:
        self.cfg = cfg

    # ---------- 内部 ----------
    def _url(self) -> str:
        base = self.cfg.base_url.rstrip("/")
        if base.endswith("/chat/completions"):
            return base
        return base + "/chat/completions"

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.cfg.api_key:
            headers["Authorization"] = f"Bearer {self.cfg.api_key}"
        return headers

    # ---------- 对外 ----------
    def chat(
        self,
        messages: Sequence[Message],
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> ChatResult:
        payload: dict[str, Any] = {
            "model": self.cfg.name,
            "messages": list(messages),
            "temperature": self.cfg.temperature if temperature is None else temperature,
            "max_tokens": self.cfg.max_tokens if max_tokens is None else max_tokens,
            "stream": False,
        }
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            self._url(), data=data, headers=self._headers(), method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=self.cfg.timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:400]
            raise LLMError(
                f"HTTP {exc.code} from {self._url()}: {body}"
            ) from exc
        except urllib.error.URLError as exc:
            raise LLMError(
                f"无法连接模型服务 {self._url()}（{exc.reason}）。"
                "检查 MEMOIR_BASE_URL 是否正确、本地模型是否已启动。"
            ) from exc
        except (socket.timeout, TimeoutError) as exc:
            raise LLMError(
                f"模型响应超时（{self.cfg.timeout}s），可调大 MEMOIR_TIMEOUT。"
            ) from exc

        try:
            obj = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise LLMError(f"响应不是 JSON: {raw[:200]}") from exc

        try:
            text = obj["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"响应结构不符合 OpenAI 格式: {raw[:200]}") from exc

        usage = obj.get("usage") or {}
        return ChatResult(
            text=text or "",
            model=str(obj.get("model", self.cfg.name)),
            tokens=int(usage.get("total_tokens", 0) or 0),
        )

    def health(self) -> tuple[bool, str]:
        """探活：发一个最短请求，判断模型是否真的可用。"""
        try:
            res = self.chat(
                [{"role": "user", "content": "ping"}], max_tokens=8, temperature=0
            )
            return True, res.text.strip()[:60] or "(空响应)"
        except LLMError as exc:
            return False, str(exc)


def extract_json(text: str) -> Any:
    """从模型输出里抠出第一个 JSON 对象/数组。

    兼容三种常见脏输出：代码围栏、前置解释、尾部多余文字。
    """
    s = (text or "").strip()
    if s.startswith("```"):
        lines = s.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        s = "\n".join(lines).strip()

    # 按"最先出现的括号"决定解析对象还是数组，避免
    # "前言 [{...}] 后记" 被当成 object 抠出来
    candidates: list[tuple[int, str]] = []
    for opener, closer in (("{", "}"), ("[", "]")):
        start = s.find(opener)
        end = s.rfind(closer)
        if start != -1 and end > start:
            candidates.append((start, s[start : end + 1]))
    for _, candidate in sorted(candidates, key=lambda c: c[0]):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return None
