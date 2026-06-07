"""SubAgent 子系统 — 参照 Claude Code md14 设计。

对外仅暴露：
- `AgentDefinition`  — 子 Agent 数据蓝图
- `SubagentContext`  — 子 Agent 执行上下文
- `run_agent`        — 派遣并执行子 Agent
- 内置 agents：`EXPLORE_AGENT` / `PLAN_AGENT` / `GENERAL_PURPOSE_AGENT`
- `get_agent_definition` / `list_agent_definitions` — 注册表查询
- `AgentTool`        — 暴露给 LLM 的派遣工具
- `MAX_AGENT_DEPTH`  — 嵌套保护上限
"""

from agents.agent_tool import AgentTool
from agents.built_in import (
    EXPLORE_AGENT,
    GENERAL_PURPOSE_AGENT,
    PLAN_AGENT,
    get_agent_definition,
    list_agent_definitions,
)
from agents.context import (
    MAX_AGENT_DEPTH,
    SubagentContext,
    build_subagent_registry,
    create_subagent_context,
)
from agents.definition import AgentDefinition
from agents.runner import run_agent

__all__ = [
    "AgentDefinition",
    "AgentTool",
    "EXPLORE_AGENT",
    "GENERAL_PURPOSE_AGENT",
    "MAX_AGENT_DEPTH",
    "PLAN_AGENT",
    "SubagentContext",
    "build_subagent_registry",
    "create_subagent_context",
    "get_agent_definition",
    "list_agent_definitions",
    "run_agent",
]
