"""run_agent — 子 Agent 的执行入口（生成器，流式 yield）。

对应 md14 §二 `runAgent()` 6-Phase 生命周期。MyCLI 没有 React/AppState/
MCP/Skills/sidechain，所以 Phase 拆解被压缩成：

  Phase 1  初始化：建子 context、生成 agent_id、构造子 prompt
  Phase 2  工具集与 LLM：build_subagent_registry、按 model 覆盖切换 LLM
  Phase 3  实例化子 ReActAgent
  Phase 4  对话循环：直接复用 ReActAgent.run_stream
  Phase 5  清理：finally 关闭子 registry 的 closers（如 MCP 子进程）
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Generator, Optional

from agents.context import (
    MAX_AGENT_DEPTH,
    SubagentContext,
    build_subagent_registry,
    create_subagent_context,
)

if TYPE_CHECKING:
    from agents.definition import AgentDefinition
    from core.llm import OpenAICompatLLM
    from tools.registry import ToolRegistry


def _clone_llm_with_model(base_llm: "OpenAICompatLLM", model: str) -> "OpenAICompatLLM":
    """生成一个 model 被覆盖的 LLM 副本。

    设计取舍：直接 ``deepcopy`` 会把 OpenAI client 也复制；而 client 自身
    持有连接池，复制后行为不可控。这里采用「构造新的 OpenAICompatLLM、
    共享同一个 config dict 的浅拷贝（仅改 model 字段）」的做法 — 子 Agent
    用完后丢弃，不影响父 Agent 的 config 引用。
    """
    from core.llm import OpenAICompatLLM

    child_config = dict(base_llm.config)
    child_config["model"] = model
    return OpenAICompatLLM(child_config)


def run_agent(
    *,
    parent_ctx: Optional[SubagentContext],
    parent_registry: "ToolRegistry",
    base_llm: "OpenAICompatLLM",
    agent_definition: "AgentDefinition",
    prompt: str,
    parent_history: Optional[list] = None,
) -> Generator[str, None, None]:
    """派遣并流式执行一个子 Agent。

    参数：
        parent_ctx        : 父级 SubagentContext；根 ReActAgent 派遣时为 None
        parent_registry   : 父级工具注册表（用于推导子 registry）
        base_llm          : 父级 LLM 实例（用于继承 config / 仅在 model 覆盖时换实例）
        agent_definition  : 子 Agent 蓝图
        prompt            : 父 Agent 给子 Agent 的任务描述（must be self-contained）
        parent_history    : 父对话历史；当 ``inherit_history=True`` 时被透传

    Yields:
        子 Agent 输出的文本片段（包含工具调用提示等）。

    Raises:
        RuntimeError : 超过 ``MAX_AGENT_DEPTH``（按 md14 §三全局禁止策略）
    """
    # 延迟导入避免 agents/runner.py ↔ core/reagent.py ↔ tools/builtin.py 循环
    from core.reagent import ReActAgent

    # Phase 1 — 构建子 context（默认隔离）
    sub_ctx = create_subagent_context(parent_ctx, parent_registry, agent_definition)

    # 嵌套保护：双保险。第一层是 build_subagent_registry 不会把 AgentTool 拷
    # 进去；这里再额外检查一次 depth，防止有人手工调用 run_agent 跨深度。
    if sub_ctx.depth > MAX_AGENT_DEPTH:
        raise RuntimeError(
            f"子 Agent 嵌套深度 {sub_ctx.depth} 超过上限 {MAX_AGENT_DEPTH}；"
            "MyCLI 默认不允许子 Agent 再派遣子 Agent。"
        )

    # Phase 2 — 构建子 registry + 可能切换 LLM
    sub_registry = build_subagent_registry(parent_registry, agent_definition)
    sub_llm = (
        _clone_llm_with_model(base_llm, agent_definition.model)
        if agent_definition.model
        else base_llm
    )

    # Phase 3 — 实例化子 ReActAgent
    sub_agent = ReActAgent(
        name=f"{agent_definition.agent_type}#{sub_ctx.agent_id}",
        llm=sub_llm,
        tool_registry=sub_registry,
        max_steps=agent_definition.max_steps,
        custom_prompt=agent_definition.system_prompt,
        parent_ctx=sub_ctx,
    )

    # Phase 4 — 对话循环；Phase 5 — 清理
    history = parent_history if agent_definition.inherit_history else None
    try:
        yield from sub_agent.run_stream(prompt, history=history)
    finally:
        # 关闭子 registry 持有的 closers（与 md14 Phase 6 的 mcpCleanup 对齐）。
        # 注意：sub_registry 是新建的空 registry，把父级 tool 实例引用拷了进来，
        # 但 closers 列表本身是空的（只有原父 registry 的 closers 在工作）。
        # 这里调用是为了未来在子 registry 上动态注册资源时不留漏洞。
        try:
            sub_registry.close()
        except Exception:
            pass
