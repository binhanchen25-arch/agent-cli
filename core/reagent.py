"""Agent 模块 — 基于 OpenAI Function Calling 的智能体，支持并行工具调用。"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING, Generator, List, Optional

if TYPE_CHECKING:
    from core.llm import OpenAICompatLLM

from tools.base import UserRefusedError
from tools.builtin import default_tool_registry
from tools.registry import ToolRegistry

AGENT_SYSTEM_PROMPT = """你是一个强大的 AI 助手，可以调用工具来完成任务。
当你需要获取信息时，请使用可用的工具。你可以在一次回复中调用多个工具来并行获取信息。
当你有足够信息回答用户问题时，直接用文本回复，不要调用工具。
阅读代码时，先用 tree/glob 了解结构，再用 grep 定位关键词，最后用 view 读取相关片段。不要试图一次读完整个文件。"""


class ReActAgent:
    """
    基于 OpenAI Function Calling 的智能体：LLM 可一次返回多个 tool_calls，
    按序执行后将结果一起喂回，大幅减少对话轮次。
    """

    def __init__(
        self,
        name: str,
        llm: OpenAICompatLLM,
        tool_registry: Optional[ToolRegistry] = None,
        max_steps: int = 20,
        custom_prompt: Optional[str] = None,
    ) -> None:
        self.name = name
        self.llm = llm
        self.tool_registry = tool_registry or default_tool_registry()
        self.max_steps = max_steps
        self.system_prompt = custom_prompt or AGENT_SYSTEM_PROMPT

    def run(self, question: str) -> str:
        """执行 Function Calling 循环，返回最终文本回复。"""
        from cli.renderer import console

        if not self.llm.config.get("api_key"):
            return "Agent 模式需要配置 API Key（环境变量 OPENAI_API_KEY 或配置文件中的 api_key）。"

        messages: List[dict] = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": question},
        ]
        tools_schema = self.tool_registry.get_openai_tools_schema()
        total_calls = 0

        with console.status("🤔 Thinking…", spinner="dots") as status:
            for step in range(1, self.max_steps + 1):
                status.update(f"🤔 Thinking… (step {step}/{self.max_steps})")

                resp = self.llm.invoke_with_tools(messages, tools_schema)

                # 没有工具调用 → LLM 直接给出最终回答
                if not resp.tool_calls:
                    return resp.content or "（无回复）"

                # 将带 tool_calls 的 assistant 消息追加到历史
                assistant_msg: dict = {
                    "role": "assistant",
                    "content": resp.content or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                            },
                        }
                        for tc in resp.tool_calls
                    ],
                }
                messages.append(assistant_msg)

                # 按序执行每个 tool call，结果作为 tool 消息追加
                for tc in resp.tool_calls:
                    total_calls += 1
                    status.update(f"🔧 Running: {tc.name} ({total_calls} calls)")

                    try:
                        result = self.tool_registry.execute_tool_by_params(
                            tc.name, tc.arguments
                        )
                    except UserRefusedError as e:
                        # 用户拒绝 → 记录拒绝结果并让 LLM 基于已有信息回复
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": f"用户拒绝: {e.detail}",
                        })
                        return self._finish_on_refused(messages)

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result,
                    })

        return "抱歉，在限定步数内未能完成任务。"

    def _finish_on_refused(self, messages: List[dict]) -> str:
        """用户拒绝后，让 LLM 基于完整上下文给出最终回复。"""
        messages.append({
            "role": "user",
            "content": "用户拒绝了上述工具的执行。请根据已有信息给出最佳回答，"
                       "或说明为什么需要执行该操作。",
        })
        return self.llm.invoke(messages)


class ReActChatLLM:
    """
    将 ReActAgent 适配成 ChatApp 期望的 llm 接口：提供 invoke()/stream()。
    """

    def __init__(self, agent: ReActAgent) -> None:
        self.agent = agent

    def invoke(self, messages: List[dict]) -> str:
        question = ""
        if messages:
            question = str(messages[-1].get("content", ""))
        return self.agent.run(question)

    def stream(self, messages: List[dict]) -> Generator[str, None, None]:
        from core.llm import stream_text

        yield from stream_text(self.invoke(messages))
