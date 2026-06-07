"""AgentTool — 暴露给父 LLM 的「派遣子 Agent」工具。

对应 md14 中的 `AgentTool`（`tools/AgentTool/`）。MyCLI 把它实现为一个普通
``Tool`` 子类，注册到父 Agent 的 ToolRegistry；当 LLM 调用 `agent`
工具时，触发 ``run_agent`` 并把子 Agent 的最终文本作为单个工具结果回传。

为什么子 Agent 输出做"折叠返回"而不是"流式回传"？
- OpenAI Function Calling 协议要求 tool result 是单条字符串。
- 父 Agent 真正在意的只是「子 Agent 的结论」，中间步骤的可观察性留给
  CLI status 行（未来可加），不进入父对话上下文 — 这正是子 Agent 用于
  「上下文隔离」的核心价值（md14 §为什么需要多 Agent）。
"""

from __future__ import annotations

from io import StringIO
from typing import Any, Dict, List, Optional

from agents.built_in import get_agent_definition, list_agent_definitions
from agents.context import MAX_AGENT_DEPTH, SubagentContext
from agents.runner import run_agent
from tools.base import Tool, ToolParameter


def _build_description() -> str:
    """汇总所有内置 Agent 的简介，作为 AgentTool 自身的 description。

    这样模型在 Function Calling 时能在一处看到全部可选的 ``subagent_type``。
    """
    lines: List[str] = [
        "派遣一个具有独立上下文与独立工具集的子 Agent 完成自包含子任务，",
        "只把最终结论回传父 Agent（中间步骤不进入主对话）。",
        "",
        "可选的 subagent_type：",
    ]
    for d in list_agent_definitions():
        lines.append(f"- `{d.agent_type}`: {d.description}")
        lines.append(f"  适用场景: {d.when_to_use}")
    return "\n".join(lines)


class AgentTool(Tool):
    """父 Agent 用来派遣子 Agent 的 Function-Calling 工具。"""

    search_hint = "派遣子 Agent，把多步子任务隔离到独立上下文"

    def __init__(
        self,
        parent_registry,
        base_llm,
        *,
        parent_ctx: Optional[SubagentContext] = None,
    ) -> None:
        super().__init__(
            name="agent",
            description=_build_description(),
            expandable=False,
        )
        self._parent_registry = parent_registry
        self._base_llm = base_llm
        self._parent_ctx = parent_ctx  # None = 由根 ReActAgent 调用

    # ── Tool 协议 ──

    def get_parameters(self) -> List[ToolParameter]:
        agent_types = ", ".join(d.agent_type for d in list_agent_definitions())
        return [
            ToolParameter(
                name="subagent_type",
                type="string",
                description=f"子 Agent 类型，必须是以下之一：{agent_types}",
                required=True,
            ),
            ToolParameter(
                name="prompt",
                type="string",
                description=(
                    "给子 Agent 的完整任务描述。必须是自包含的 — 子 Agent 看不到"
                    "父对话历史（除非该 Agent 显式 inherit_history），所有需要"
                    "的背景必须在 prompt 里说清楚。"
                ),
                required=True,
            ),
            ToolParameter(
                name="description",
                type="string",
                description="一句话任务描述，未来会在状态行显示。可选。",
                required=False,
                default="",
            ),
        ]

    def is_read_only(self, parameters: Optional[Dict[str, Any]] = None) -> bool:
        # 子 Agent 可能调用任意工具（取决于 subagent_type），保守起见非只读。
        return False

    def is_concurrency_safe(self, parameters: Optional[Dict[str, Any]] = None) -> bool:
        # 子 Agent 自带工具并发，再被父级并行调用容易把 CLI 弹窗/输出搞混。
        return False

    def is_destructive(self, parameters: Optional[Dict[str, Any]] = None) -> bool:
        # 让 General-purpose 子 Agent 这类全工具变体能被默认行为兜底确认。
        sub_type = (parameters or {}).get("subagent_type", "")
        defn = get_agent_definition(sub_type)
        if defn is None:
            return True  # 未知类型保守一刀
        # 没有写工具 = 只读 Agent，按非破坏处理；否则按潜在破坏处理。
        return not _is_read_only_definition(defn)

    def run(self, parameters: Dict[str, Any]) -> str:
        sub_type = str(parameters.get("subagent_type", "")).strip()
        prompt = str(parameters.get("prompt", "")).strip()

        if not sub_type:
            return self._err_unknown_type("(空)")
        if not prompt:
            return "错误：必须提供非空 `prompt`。子 Agent 需要自包含的任务描述。"

        definition = get_agent_definition(sub_type)
        if definition is None:
            return self._err_unknown_type(sub_type)

        # 深度保护：当前层级（parent_ctx.depth）+ 即将生成的子 Agent 深度 +1
        # 必须 ≤ MAX_AGENT_DEPTH。
        current_depth = self._parent_ctx.depth if self._parent_ctx else 0
        if current_depth >= MAX_AGENT_DEPTH:
            return (
                f"错误：当前已位于嵌套深度 {current_depth}，"
                f"不允许继续派遣子 Agent（上限 {MAX_AGENT_DEPTH}）。"
            )

        # 收集子 Agent 的所有流式输出，折叠成一段文本作为 tool result。
        buf = StringIO()
        try:
            for chunk in run_agent(
                parent_ctx=self._parent_ctx,
                parent_registry=self._parent_registry,
                base_llm=self._base_llm,
                agent_definition=definition,
                prompt=prompt,
            ):
                buf.write(chunk)
        except Exception as e:
            return (
                f"子 Agent `{sub_type}` 执行失败：{type(e).__name__}: {e}"
            )

        body = buf.getvalue().strip() or "（子 Agent 未输出内容）"
        return f"=== Subagent `{sub_type}` 结论 ===\n{body}"

    # ── helpers ──

    @staticmethod
    def _err_unknown_type(name: str) -> str:
        avail = ", ".join(d.agent_type for d in list_agent_definitions())
        return f"未知 subagent_type `{name}`。可选：{avail}"


def _is_read_only_definition(defn) -> bool:
    """启发式判定：若 disallowed_tools 覆盖了所有已知的写工具，视为只读。"""
    # 与 built_in._WRITE_TOOLS 解耦：这里只看「是否禁用了至少一个常见写工具」
    write_indicators = {"write_file", "edit_file", "windows_cmd", "python_repl"}
    return bool(set(defn.disallowed_tools) & write_indicators)
