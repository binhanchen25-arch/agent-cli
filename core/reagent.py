"""Agent 模块 — 基于 OpenAI Function Calling 的智能体，支持并行工具调用。"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TYPE_CHECKING, Callable, Generator, List, Optional

if TYPE_CHECKING:
    from agents.context import SubagentContext
    from core.llm import OpenAICompatLLM

from core.hooks import get_hook
from tools.base import UserRefusedError
from tools.builtin import default_tool_registry
from tools.registry import ToolRegistry

# before_step hook 的签名：
#   (step: int, messages: list[dict]) -> list[dict] | None
# 返回 None → 不变；返回 list → 替换 messages。
BeforeStepHook = Callable[[int, List[dict]], Optional[List[dict]]]

AGENT_SYSTEM_PROMPT = """你是 MyCLI 的 ReAct Agent，擅长在终端与代码库场景中通过工具完成任务。

核心目标：
- 用尽可能少的步骤得到正确结果。
- 在信息不足时先获取证据，不凭空猜测。
- 当信息已足够时立即停止调用工具并给出最终答案。

工具调用规则：
- 需要外部信息时再调用工具；不需要就直接回答。
- 可以在同一轮并行调用多个独立工具以提速。
- 参数必须具体、可执行，避免宽泛或重复查询。
- 不确定是否存在某个能力时，先用 `tool_search` 按关键词检索；命中的工具会自动进入下一轮可用集合。
- 若 system 消息里出现 `<available-deferred-tools>` 块，说明里面列出的工具当前不在 schema 中，只有名字和一句话提示；要使用时先调用 `tool_search`（关键词搜索或 `select:工具名` 精确加载）拿到完整参数定义。
- 每次工具调用都必须显式传入 confirm 参数，由你自主判断：
  · 只读/查询类工具（如 view、grep、glob、tree、web_search、fetch_url、now、echo）→ confirm=false。
  · 高风险/不可逆操作（如 write_file、edit_file、file_ops、windows_cmd、python_repl、create_docx）→ confirm=true。
  · 参数不明确或可能误伤多文件/资源时 → confirm=true。
- 工具失败时先缩小范围重试一次；仍失败则说明原因并给替代方案。

代码库阅读策略：
- 先用 tree/glob 了解结构。
- 再用 grep 精确定位符号或关键词。
- 最后用 view 只读取必要片段。
- 不要一次读取完整大文件。

安全与输出：
- 涉及删除、覆盖、提权、网络暴露等高风险操作，先提示风险。
- 默认中文，回答简洁：先结论，再给关键步骤/命令。
- 最终回复必须基于已知证据；不确定时明确说明不确定点。"""


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
        before_step: Optional[BeforeStepHook] = None,
        parent_ctx: Optional["SubagentContext"] = None,
    ) -> None:
        self.name = name
        self.llm = llm
        self.tool_registry = tool_registry or default_tool_registry()
        self.max_steps = max_steps
        self.system_prompt = custom_prompt or AGENT_SYSTEM_PROMPT
        # 显式传入优先；否则尝试从 ~/.mycli/hooks.py 加载
        self.before_step: Optional[BeforeStepHook] = before_step or get_hook("before_step")
        # 由 agents.runner.run_agent 注入；根 Agent 为 None。
        # 用于在工具内（如 AgentTool）判断当前嵌套深度。
        self.parent_ctx: Optional["SubagentContext"] = parent_ctx

    def _build_initial_messages(self, question: str, history: Optional[List[dict]] = None) -> List[dict]:
        """构造 ReAct 初始消息：system + 历史 + 当前问题。"""
        messages: List[dict] = [{"role": "system", "content": self.system_prompt}]

        if history:
            for msg in history:
                if not isinstance(msg, dict):
                    continue
                role = msg.get("role")
                if role not in ("user", "assistant"):
                    # CLI 历史里主要是 user/assistant；其他角色先忽略，避免污染输入。
                    continue
                content = str(msg.get("content", ""))
                if not content:
                    continue
                messages.append({"role": role, "content": content})

        messages.append({"role": "user", "content": question})
        return messages

    def run(self, question: str, history: Optional[List[dict]] = None) -> str:
        """执行 Function Calling 循环，返回最终文本回复（非流式，保留以兼容旧调用）。"""
        # 复用 run_stream，把流式 token 拼起来作为最终结果
        return "".join(self.run_stream(question, history=history))

    def run_stream(self, question: str, history: Optional[List[dict]] = None) -> Generator[str, None, None]:
        """
        流式执行 Function Calling 循环：
            - LLM 输出的 token 实时 yield
            - 工具调用 / 状态提示以 Markdown 片段形式 yield 到同一对话面板
            - 消费方按 Ctrl+C 触发 GeneratorExit 时，会清理 status / HTTP 连接
        """
        from cli.renderer import console

        if not self.llm.config.get("api_key"):
            yield "Agent 模式需要配置 API Key（环境变量 OPENAI_API_KEY 或配置文件中的 api_key）。"
            return

        messages = self._build_initial_messages(question, history=history)
        total_calls = 0

        status_cm = console.status("🤔 Thinking…", spinner="dots")
        status = status_cm.__enter__()
        try:
            for step in range(1, self.max_steps + 1):
                status.update(f"🤔 Thinking… (step {step}/{self.max_steps})")

                # 用户钩子
                if self.before_step is not None:
                    try:
                        new_messages = self.before_step(step, messages)
                        if isinstance(new_messages, list):
                            messages = new_messages
                    except Exception as e:
                        yield f"\n\n> ⚠️ before_step hook 异常已忽略: `{e}`\n\n"

                # 每轮重算 schema：tool_search 可能在上一轮把新工具加入 discovered。
                tools_schema = self.tool_registry.get_openai_tools_schema()

                # 每轮临时拼接 deferred 列表到 system prompt。不修改原 messages，
                # 以便后续在历史中保留纯净的 system 提示。
                send_messages = self._augment_with_deferred(messages)

                # 真流式调用 LLM
                final_resp = None
                tool_calls: List = []
                inner_stream = self.llm.stream_with_tools(send_messages, tools_schema)
                try:
                    for event_type, payload in inner_stream:
                        if event_type == "content":
                            yield payload  # ← 实时透传 token
                        elif event_type == "tool_calls":
                            tool_calls = payload
                        elif event_type == "done":
                            final_resp = payload
                finally:
                    # 我们被 close() 时，确保底层 LLM 流也关闭（释放 HTTP 连接）
                    close = getattr(inner_stream, "close", None)
                    if callable(close):
                        try:
                            close()
                        except Exception:
                            pass

                # 没有工具调用 → LLM 已直接给出最终回答（token 已 yield 完）
                if not tool_calls:
                    return

                # 提示用户：模型决定调用工具
                names = ", ".join(f"`{tc.name}`" for tc in tool_calls)
                # yield f"\n\n> 🔧 调用工具：{names}\n\n"

                # 把带 tool_calls 的 assistant 消息追加到历史
                messages.append({
                    "role": "assistant",
                    "content": (final_resp.content if final_resp else "") or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                            },
                        }
                        for tc in tool_calls
                    ],
                })

                # 按 partition 调度：相邻 concurrency_safe 的工具合并为一个并发 batch；
                # 其他工具串行。任一被拒绝（UserRefusedError）则按原逻辑收尾。
                batches = self.tool_registry.partition_tool_calls(tool_calls)
                for is_concurrent, batch in batches:
                    if is_concurrent and len(batch) > 1:
                        # 并发批
                        names_str = ", ".join(tc.name for tc in batch)
                        total_calls += len(batch)
                        status.update(
                            f"🔧 Running {len(batch)} tools in parallel: {names_str}"
                        )

                        results: List = [None] * len(batch)
                        with ThreadPoolExecutor(
                            max_workers=min(10, len(batch))
                        ) as executor:
                            future_to_idx = {
                                executor.submit(
                                    self.tool_registry.execute_tool_by_params,
                                    tc.name,
                                    tc.arguments,
                                ): i
                                for i, tc in enumerate(batch)
                            }
                            for future in as_completed(future_to_idx):
                                idx = future_to_idx[future]
                                try:
                                    results[idx] = future.result()
                                except UserRefusedError as e:
                                    # 并发模式下 concurrency_safe 工具一般不会触发确认弹窗，
                                    # 但若用户在 hooks 中改变了策略，保留兜底处理。
                                    results[idx] = e

                        # 先把所有结果按原顺序追加（保证 tool_call_id 与 batch 顺序一致），
                        # 再检查是否有拒绝事件。
                        refused_idx = -1
                        for i, (tc, result) in enumerate(zip(batch, results)):
                            if isinstance(result, UserRefusedError):
                                messages.append({
                                    "role": "tool",
                                    "tool_call_id": tc.id,
                                    "content": f"用户拒绝: {result.detail}",
                                })
                                if refused_idx < 0:
                                    refused_idx = i
                            else:
                                messages.append({
                                    "role": "tool",
                                    "tool_call_id": tc.id,
                                    "content": result,
                                })

                        if refused_idx >= 0:
                            yield (
                                f"\n> ❌ 用户拒绝执行 "
                                f"`{batch[refused_idx].name}`\n\n"
                            )
                            yield self._finish_on_refused(messages)
                            return
                        continue

                    # 串行批：单个工具或非并发安全
                    for tc in batch:
                        total_calls += 1
                        status.update(
                            f"🔧 Running: {tc.name} ({total_calls} calls)"
                        )

                        try:
                            result = self.tool_registry.execute_tool_by_params(
                                tc.name, tc.arguments
                            )
                        except UserRefusedError as e:
                            messages.append({
                                "role": "tool",
                                "tool_call_id": tc.id,
                                "content": f"用户拒绝: {e.detail}",
                            })
                            yield f"\n> ❌ 用户拒绝执行 `{tc.name}`\n\n"
                            yield self._finish_on_refused(messages)
                            return

                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": result,
                        })

            yield "\n\n抱歉，在限定步数内未能完成任务。"
        finally:
            status_cm.__exit__(None, None, None)

    def _finish_on_refused(self, messages: List[dict]) -> str:
        """用户拒绝后，让 LLM 基于完整上下文给出最终回复。"""
        messages.append({
            "role": "user",
            "content": "用户拒绝了上述工具的执行。请根据已有信息给出最佳回答，"
                       "或说明为什么需要执行该操作。",
        })
        return self.llm.invoke(messages)

    # ── deferred-tools 提醒 ──

    @staticmethod
    def _format_deferred_block(deferred: List[dict]) -> str:
        """组装 ``<available-deferred-tools>`` 提醒块。"""
        lines = ["<available-deferred-tools>"]
        for item in deferred:
            name = item.get("name", "")
            hint = item.get("hint", "")
            lines.append(f"- {name}: {hint}" if hint else f"- {name}")
        lines.append("</available-deferred-tools>")
        lines.append(
            "上述工具不在当前 schema 中。需要使用时，先调用 `tool_search`（关键词检索"
            "或 `select:工具名` 精确加载）拿到参数定义后再调用。"
        )
        return "\n".join(lines)

    def _augment_with_deferred(self, messages: List[dict]) -> List[dict]:
        """返回一个新的 messages 列表：如果存在 deferred 工具，则在首个 system
        消息末尾拼接 ``<available-deferred-tools>`` 提醒块。原 messages 保持不变。
        """
        deferred = self.tool_registry.list_deferred_tools()
        if not deferred:
            return messages
        block = self._format_deferred_block(deferred)
        if messages and messages[0].get("role") == "system":
            new_sys = {
                **messages[0],
                "content": (messages[0].get("content") or "") + "\n\n" + block,
            }
            return [new_sys] + messages[1:]
        # 没有 system 头（理论上不应该走到这，但作为兑底）
        return [{"role": "system", "content": block}] + messages


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
        history = messages[:-1] if len(messages) > 1 else []
        return self.agent.run(question, history=history)

    def stream(self, messages: List[dict]) -> Generator[str, None, None]:
        """真流式：直接转发 agent.run_stream 的 token / 状态片段。"""
        question = ""
        if messages:
            question = str(messages[-1].get("content", ""))
        history = messages[:-1] if len(messages) > 1 else []
        yield from self.agent.run_stream(question, history=history)
