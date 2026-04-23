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

    def _get_client(self):
        """获取或创建 OpenAI client，仅在 api_key/base_url 变更时重建。"""
        from openai import OpenAI

        key = (self.config["api_key"], self.config["base_url"])
        if self._client is None or self._client_key != key:
            self._client = OpenAI(api_key=key[0], base_url=key[1])
            self._client_key = key
        return self._client

    def invoke(self, messages: List[dict]) -> str:
        try:
            client = self._get_client()
            response = client.chat.completions.create(
                model=self.config["model"],
                messages=messages,
                max_tokens=self.config["max_tokens"],
                temperature=self.config["temperature"],
                stream=False,
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
            response = client.chat.completions.create(**kwargs)
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

    def stream(self, messages: List[dict]) -> Generator[str, None, None]:
        try:
            client = self._get_client()
            response = client.chat.completions.create(
                model=self.config["model"],
                messages=messages,
                max_tokens=self.config["max_tokens"],
                temperature=self.config["temperature"],
                stream=True,
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
    "帮助": "## 📖 使用帮助\n\n| 命令 | 说明 |\n|------|------|\n| `/help` | 显示帮助信息 |\n| `/clear` | 清空对话历史 |\n| `/config` | 查看当前配置 |\n| `/model <name>` | 切换模型 |\n| `/react` | 切换到 ReAct 模式（之后输入会走 Agent；需 API Key） |\n| `/react <问题>` | 切到 ReAct 并立即执行一次 |\n| `/allow` 或 `/allow all` | 允许命令工具直接执行（跳过 Yes/No） |\n| `/allow off` | 关闭直通执行，恢复 Yes/No 确认 |\n| `/chat` 或 `/normal` | 切回普通聊天模式 |\n| `/exit` | 退出程序 |\n\n直接输入文字即可开始对话。",
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
