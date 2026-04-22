"""ReAct Agent — 推理与行动结合，适用于本终端项目的 dict 配置与 OpenAI 兼容 API。"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING, Generator, List, Optional, Tuple

if TYPE_CHECKING:
    from core.llm import OpenAICompatLLM

from tools.base import UserRefusedError
from tools.builtin import default_tool_registry
from tools.registry import ToolRegistry

DEFAULT_REACT_PROMPT = """你是一个具备推理和行动能力的 AI 助手。你可以通过思考分析问题，然后调用合适的工具来获取信息，最终给出准确的答案。

## 可用工具
{tools}

## 工作流程
请严格按照以下格式进行回应，每次只能执行一个步骤：

Thought: 分析问题，确定需要什么信息，制定研究策略。
Action: 选择合适的工具获取信息，格式为：
- `{{tool_name}}[{{tool_input}}]`：调用工具获取信息。
- `Finish[最终结论]`：当你有足够信息得出结论时。

## 重要提醒
1. 每次回应必须包含 Thought 和 Action 两部分
2. 工具调用的格式必须严格遵循：工具名[参数]
3. 只有当你确信有足够信息回答问题时，才使用 Finish
4. 如果工具返回的信息不够，继续使用其他工具或相同工具的不同参数

## 当前任务
**Question:** {question}

## 执行历史
{history}

现在开始你的推理和行动："""


class ReActAgent:
    """
    ReAct（Reasoning + Acting）智能体：多步 Thought → Action → Observation，直到 Finish。
    依赖 `OpenAICompatLLM.invoke()`，与 ChatApp 中持有的 llm 为同一实例。
    """

    def __init__(
        self,
        name: str,
        llm: OpenAICompatLLM,
        tool_registry: Optional[ToolRegistry] = None,
        max_steps: int = 8,
        custom_prompt: Optional[str] = None,
    ) -> None:
        self.name = name
        self.llm = llm
        self.tool_registry = tool_registry or default_tool_registry()
        self.max_steps = max_steps
        self.prompt_template = custom_prompt or DEFAULT_REACT_PROMPT
        self.current_history: List[str] = []

    def run(self, question: str) -> str:
        """执行 ReAct 循环，返回最终答案字符串。"""
        from cli.renderer import console

        self.current_history = []
        if not self.llm.config.get("api_key"):
            return "ReAct 模式需要配置 API Key（环境变量 OPENAI_API_KEY 或配置文件中的 api_key）。"

        with console.status("🤔 Thinking…", spinner="dots") as status:
            for step in range(1, self.max_steps + 1):
                status.update(f"🤔 Thinking… (step {step}/{self.max_steps})")
                tools_desc = self.tool_registry.get_tools_description()
                history_str = "\n".join(self.current_history) if self.current_history else "（尚无）"
                prompt = self.prompt_template.format(
                    tools=tools_desc,
                    question=question,
                    history=history_str,
                )
                messages: List[dict] = []
                sp = self.llm.config.get("system_prompt")
                if sp:
                    messages.append({"role": "system", "content": sp})
                messages.append({"role": "user", "content": prompt})

                response_text = self.llm.invoke(messages)
                if not response_text:
                    break

                thought, action = self._parse_output(response_text)
                if not action:
                    break

                if action.startswith("Finish"):
                    return self._parse_action_input(action)

                tool_name, tool_input = self._parse_action(action)
                if not tool_name or tool_input is None:
                    self.current_history.append(f"Action: {action}")
                    self.current_history.append(
                        "Observation: Action 格式无效，应为 工具名[参数] 或 Finish[结论]。"
                    )
                    continue

                status.update(f"🔧 Running tool: {tool_name}…")
                try:
                    observation = self.tool_registry.execute_tool(tool_name, tool_input)
                except UserRefusedError as e:
                    self.current_history.append(f"Action: {action}")
                    self.current_history.append(f"Observation: {e.detail}")
                    status.update("🤔 Thinking…")
                    return self._finish_on_refused(question)

                self.current_history.append(f"Action: {action}")
                self.current_history.append(f"Observation: {observation}")

        return "抱歉，在限定步数内未能得到明确结论。"

    def _finish_on_refused(self, question: str) -> str:
        """用户拒绝工具执行后，将完整上下文交给 LLM 生成最终回复。"""
        history_str = "\n".join(self.current_history)
        prompt = (
            f"用户提出了问题：{question}\n\n"
            f"## 执行历史\n{history_str}\n\n"
            "用户拒绝了上述命令的执行。请根据已有信息给出你能提供的最佳回答，"
            "或者告知用户如果不执行该命令你无法完成任务的原因。"
        )
        messages: List[dict] = []
        sp = self.llm.config.get("system_prompt")
        if sp:
            messages.append({"role": "system", "content": sp})
        messages.append({"role": "user", "content": prompt})
        return self.llm.invoke(messages)

    def _parse_output(self, text: str) -> Tuple[Optional[str], Optional[str]]:
        thought_m = re.search(r"Thought:\s*(.+?)(?=\n\s*Action:|\Z)", text, re.DOTALL | re.IGNORECASE)
        action_m = re.search(r"Action:\s*(.+?)(?:\n\n|\nThought:|\Z)", text, re.DOTALL | re.IGNORECASE)
        thought = thought_m.group(1).strip() if thought_m else None
        action = action_m.group(1).strip() if action_m else None
        if action:
            action = " ".join(action.split())
        return thought, action

    def _parse_action(self, action_text: str) -> Tuple[Optional[str], Optional[str]]:
        """解析 `toolname[args]`，支持 Finish[...]。"""
        m = re.match(r"(\w+)\[(.*)\]\s*$", action_text.strip(), re.DOTALL)
        if m:
            return m.group(1), m.group(2)
        return None, None

    def _parse_action_input(self, action_text: str) -> str:
        m = re.match(r"\w+\[(.*)\]\s*$", action_text.strip(), re.DOTALL)
        return m.group(1).strip() if m else ""


class ReActChatLLM:
    """
    将 ReActAgent 适配成 ChatApp 期望的 llm 接口：提供 invoke()/stream()。

    - invoke(messages) -> str：返回最终答案文本
    - stream(messages) -> Generator[str]：以单块形式流式返回最终答案

    注意：这里不做多轮 agent 记忆；question 取 messages 的最后一条 user 内容。
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
