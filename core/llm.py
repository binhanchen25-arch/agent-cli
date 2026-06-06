import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Generator, List, Optional


@dataclass
class ToolCall:
    """从 LLM 响应中解析出的单次工具调用。"""
    id: str
    name: str
    arguments: Dict[str, Any]


@dataclass
class LLMResponse:
    """LLM 响应的统一内部表示，隔离 SDK 细节。"""
    content: Optional[str] = None
    tool_calls: List[ToolCall] = field(default_factory=list)
    finish_reason: Optional[str] = None


class OpenAICompatLLM:
    """
    与 ChatApp 共享的 config 引用，统一封装「非流式 / 流式」调用。
    内部复用同一个 OpenAI client 实例，配置变更时自动重建。
    """

    def __init__(self, config: dict) -> None:
        self.config = config
        self._client: Optional[object] = None
        self._client_key: Optional[tuple] = None
        self._default_retry_times = 3
        self._default_retry_base_delay = 0.6

    def _get_client(self):
        """获取或创建 OpenAI client，仅在 api_key/base_url 变更时重建。"""
        from openai import OpenAI

        key = (self.config["api_key"], self.config["base_url"])
        if self._client is None or self._client_key != key:
            self._client = OpenAI(api_key=key[0], base_url=key[1])
            self._client_key = key
        return self._client

    def _get_retry_times(self) -> int:
        value = self.config.get("retry_times", self._default_retry_times)
        try:
            times = int(value)
        except (TypeError, ValueError):
            times = self._default_retry_times
        return max(1, times)

    def _get_retry_base_delay(self) -> float:
        value = self.config.get("retry_base_delay", self._default_retry_base_delay)
        try:
            delay = float(value)
        except (TypeError, ValueError):
            delay = self._default_retry_base_delay
        return max(0.1, delay)

    def _should_retry_exception(self, exc: Exception) -> bool:
        """仅对临时性错误重试：连接超时、限流、服务端 5xx。"""
        name = exc.__class__.__name__
        retryable_names = {
            "APIConnectionError",
            "APITimeoutError",
            "RateLimitError",
            "InternalServerError",
        }
        if name in retryable_names:
            return True

        status_code = getattr(exc, "status_code", None)
        if isinstance(status_code, int) and (status_code == 429 or status_code >= 500):
            return True

        message = str(exc).lower()
        retryable_keywords = (
            "timeout",
            "timed out",
            "connection reset",
            "temporarily unavailable",
            "service unavailable",
            "rate limit",
            "too many requests",
        )
        if any(k in message for k in retryable_keywords):
            return True

        return False

    def _call_with_retry(self, fn, action: str):
        """统一重试入口：指数退避，仅重试可恢复错误。"""
        max_attempts = self._get_retry_times()
        base_delay = self._get_retry_base_delay()
        last_exc: Optional[Exception] = None

        for attempt in range(1, max_attempts + 1):
            try:
                return fn()
            except Exception as e:
                last_exc = e
                if attempt >= max_attempts or not self._should_retry_exception(e):
                    raise
                sleep_s = base_delay * (2 ** (attempt - 1))
                # 控制上限，避免长时间阻塞
                time.sleep(min(sleep_s, 4.0))

        if last_exc is not None:
            raise last_exc
        raise RuntimeError(f"{action} 未知错误")

    def invoke(self, messages: List[dict]) -> str:
        try:
            client = self._get_client()
            response = self._call_with_retry(
                lambda: client.chat.completions.create(
                    model=self.config["model"],
                    messages=messages,
                    max_tokens=self.config["max_tokens"],
                    temperature=self.config["temperature"],
                    stream=False,
                ),
                "invoke",
            )
            choice = response.choices[0].message
            return (choice.content or "").strip()
        except ImportError:
            return "（未安装 openai 库，无法调用 API）"
        except Exception as e:
            return f"❌ API 错误: {e}"

    def invoke_with_tools(self, messages: List[dict], tools_schema: List[dict]) -> LLMResponse:
        """带工具定义的调用，返回标准化的 LLMResponse（可能包含 tool_calls）。"""
        try:
            client = self._get_client()
            kwargs: Dict[str, Any] = {
                "model": self.config["model"],
                "messages": messages,
                "max_tokens": self.config["max_tokens"],
                "temperature": self.config["temperature"],
                "stream": False,
            }
            if tools_schema:
                kwargs["tools"] = tools_schema
            response = self._call_with_retry(
                lambda: client.chat.completions.create(**kwargs),
                "invoke_with_tools",
            )
            choice = response.choices[0]
            message = choice.message

            parsed_calls: List[ToolCall] = []
            if message.tool_calls:
                for tc in message.tool_calls:
                    try:
                        args = json.loads(tc.function.arguments)
                    except (json.JSONDecodeError, TypeError):
                        args = {}
                    parsed_calls.append(ToolCall(
                        id=tc.id,
                        name=tc.function.name,
                        arguments=args,
                    ))

            return LLMResponse(
                content=(message.content or "").strip() or None,
                tool_calls=parsed_calls,
                finish_reason=choice.finish_reason,
            )
        except ImportError:
            return LLMResponse(content="（未安装 openai 库，无法调用 API）")
        except Exception as e:
            return LLMResponse(content=f"❌ API 错误: {e}")

    def stream_with_tools(
        self, messages: List[dict], tools_schema: List[dict]
    ) -> Generator[tuple, None, None]:
        """
        带工具定义的「真流式」调用。逐 chunk yield 事件：
            ("content", str)         — LLM 输出的文本碎片
            ("tool_calls", list)     — 整段流结束后累积出的工具调用（如果有）
            ("done", LLMResponse)    — 整段流结束后的完整快照
        消费方按需取 next；不取就阻塞在 yield，天然背压。
        """
        try:
            client = self._get_client()
            kwargs: Dict[str, Any] = {
                "model": self.config["model"],
                "messages": messages,
                "max_tokens": self.config["max_tokens"],
                "temperature": self.config["temperature"],
                "stream": True,
            }
            if tools_schema:
                kwargs["tools"] = tools_schema
            response = self._call_with_retry(
                lambda: client.chat.completions.create(**kwargs),
                "stream_with_tools",
            )
        except ImportError:
            yield ("content", "（未安装 openai 库，无法调用 API）")
            yield ("done", LLMResponse(content="（未安装 openai 库，无法调用 API）"))
            return
        except Exception as e:
            msg = f"❌ API 错误: {e}"
            yield ("content", msg)
            yield ("done", LLMResponse(content=msg))
            return

        # tool_calls 按 index 累积（OpenAI 流式协议）
        # index -> {"id": str, "name": str, "arguments": str（拼接中）}
        tc_buffer: Dict[int, Dict[str, str]] = {}
        content_parts: List[str] = []
        finish_reason: Optional[str] = None

        try:
            for chunk in response:
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                delta = choice.delta

                if delta and delta.content:
                    content_parts.append(delta.content)
                    yield ("content", delta.content)

                if delta and delta.tool_calls:
                    for tc_delta in delta.tool_calls:
                        idx = tc_delta.index
                        slot = tc_buffer.setdefault(
                            idx, {"id": "", "name": "", "arguments": ""}
                        )
                        if tc_delta.id:
                            slot["id"] = tc_delta.id
                        if tc_delta.function:
                            if tc_delta.function.name:
                                slot["name"] = tc_delta.function.name
                            if tc_delta.function.arguments:
                                slot["arguments"] += tc_delta.function.arguments

                if choice.finish_reason:
                    finish_reason = choice.finish_reason
        finally:
            # 消费方 GeneratorExit / 异常时也要清理底层 HTTP 连接
            close = getattr(response, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass

        # 流结束 → 把累积好的 tool_calls 整体吐出
        parsed_calls: List[ToolCall] = []
        for idx in sorted(tc_buffer.keys()):
            slot = tc_buffer[idx]
            try:
                args = json.loads(slot["arguments"]) if slot["arguments"] else {}
            except (json.JSONDecodeError, TypeError):
                args = {}
            parsed_calls.append(ToolCall(
                id=slot["id"], name=slot["name"], arguments=args,
            ))

        if parsed_calls:
            yield ("tool_calls", parsed_calls)

        yield ("done", LLMResponse(
            content="".join(content_parts).strip() or None,
            tool_calls=parsed_calls,
            finish_reason=finish_reason,
        ))

    def stream(self, messages: List[dict]) -> Generator[str, None, None]:
        try:
            client = self._get_client()
            response = self._call_with_retry(
                lambda: client.chat.completions.create(
                    model=self.config["model"],
                    messages=messages,
                    max_tokens=self.config["max_tokens"],
                    temperature=self.config["temperature"],
                    stream=True,
                ),
                "stream",
            )
            for chunk in response:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except ImportError:
            yield from mock_stream("（未安装 openai 库，使用模拟回复）\n\n")
            yield from mock_stream(f"你说的是: {messages[-1]['content']}")
        except Exception as e:
            yield f"\n❌ API 错误: {e}"


def mock_stream(text: str) -> Generator[str, None, None]:
    """模拟流式输出，用于演示"""
    for char in text:
        yield char
        time.sleep(0.02)


def stream_text(text: str) -> Generator[str, None, None]:
    """单次 yield 整段文本，便于复用 render_stream 做静态 Markdown 面板。"""
    yield text


DEMO_RESPONSES = {
    "你好": "你好！👋 我是你的终端助手，有什么可以帮你的？\n\n我可以帮你：\n- 🔧 解答编程问题\n- 📁 生成代码片段\n- 💡 提供技术方案建议\n\n直接输入你的问题就好！",
    "帮助": "## 📖 使用帮助\n\n| 命令 | 说明 |\n|------|------|\n| `/help` | 显示帮助信息 |\n| `/clear` | 清空对话历史 |\n| `/config` | 查看当前配置 |\n| `/model <name>` | 切换模型 |\n| `/context` | 查看当前消息 token 与上下文占用 |\n| `/react` | 切换到 ReAct 模式（之后输入会走 Agent；需 API Key） |\n| `/react <问题>` | 切到 ReAct 并立即执行一次 |\n| `/allow` 或 `/allow all` | 所有工具默认直通执行（跳过 Yes/No） |\n| `/allow off` | 所有工具默认恢复 Yes/No 确认 |\n| `/chat` 或 `/normal` | 切回普通聊天模式 |\n| `/exit` | 退出程序 |\n\n提示：每次工具调用还可单独传 `confirm=true/false` 覆盖默认行为。",
}


def demo_stream(user_input: str) -> Generator[str, None, None]:
    """演示模式：不需要 API Key"""
    for key, resp in DEMO_RESPONSES.items():
        if key in user_input:
            yield from mock_stream(resp)
            return

    response = (
        f"收到你的问题：**{user_input}**\n\n"
        "这是演示模式的回复。要连接真实 AI，请配置 API Key：\n\n"
        "```bash\n"
        "export OPENAI_API_KEY=sk-your-key\n"
        "```\n\n"
        "或使用 `/config` 命令设置。"
    )
    yield from mock_stream(response)
