"""SubagentContext + 工具过滤 — 参照 md14 §2.4 / §三。

设计原则（来自 md14）：
- **默认隔离，显式共享**：子 Agent 拿到的 context 默认不共享任何可变状态，
  只有少数被显式声明的字段才透传到父级。
- **三层工具过滤**：全局禁止 → 父级 disallowed → AgentDefinition 级。
- **嵌套深度限制**：禁止 AgentTool 在子 Agent 内部继续使用（对应
  md14 ALL_AGENT_DISALLOWED_TOOLS 默认包含 AGENT_TOOL_NAME）。
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, List, Optional, Set

from tools.registry import ToolRegistry

if TYPE_CHECKING:
    from agents.definition import AgentDefinition


# ── 全局常量 ──

# AgentTool 自身的名字；用于「全局禁止子 Agent 再生子 Agent」的默认策略。
AGENT_TOOL_NAME = "agent"

# 任何子 Agent 都禁用的工具集合。MyCLI 默认只放 AGENT_TOOL_NAME 进来 —
# 对应 md14 §三第一层「全局禁止」。
ALL_AGENT_DISALLOWED_TOOLS: Set[str] = {AGENT_TOOL_NAME}

# 子 Agent 嵌套深度上限。MyCLI 把它压到 1（即只允许「主 → 子」一层），
# 因为我们暂不实现 in-process teammate 这种需要二级派遣的形态。
MAX_AGENT_DEPTH = 1


# ── SubagentContext ──

@dataclass
class SubagentContext:
    """子 Agent 的执行上下文 — 对应 md14 中 `ToolUseContext` 的子版本。

    MyCLI 的 ToolUseContext 还没有正式抽象出来，所以 SubagentContext 现阶段
    仅承载「父子关系 + 隔离的可变状态」，不强行复刻 setAppState 等不存在的字段。
    """

    # 子 Agent 蓝图（不可变）
    agent_definition: "AgentDefinition"

    # 父 Agent 的工具注册表 — 用于推导子 registry 的可用工具集
    parent_registry: ToolRegistry

    # 当前嵌套深度（根 Agent = 0，第一层子 Agent = 1）
    depth: int = 0

    # 父级 SubagentContext；为 None 表示直接由根 ReActAgent 派遣
    parent: Optional["SubagentContext"] = None

    # 每个子 Agent 一个唯一 ID，便于日志/追踪
    agent_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])

    # 子 Agent 自己的 abort 信号；父级 abort 会被 wire 到这里（见 _link_abort）
    abort_event: threading.Event = field(default_factory=threading.Event)

    # 隔离：子 Agent 的 tool_search 发现集独立，不污染父级 registry._discovered
    discovered_tools: Set[str] = field(default_factory=set)

    @classmethod
    def root(cls, parent_registry: ToolRegistry) -> "SubagentContext":
        """构造一个"根上下文"占位：表示当前没有任何子 Agent 在运行。

        depth=0 时不应该被当成真正的子 Agent 使用；它只是给 AgentTool 一个
        统一的入口来判断"我现在的层级"。
        """
        from agents.definition import AgentDefinition  # 延迟导入避免循环

        return cls(
            agent_definition=AgentDefinition(
                agent_type="__root__",
                description="占位 root context",
                when_to_use="",
                system_prompt="(root)",
            ),
            parent_registry=parent_registry,
            depth=0,
            parent=None,
        )


# ── 隔离工厂 ──

def _link_abort(child: threading.Event, parent: Optional[threading.Event]) -> None:
    """让父 abort 自动传播给子 — 模拟 createChildAbortController 行为。

    实现策略：起一个守护线程等父事件，触发后 set 子事件。子单独被 abort 时
    不会影响父（这正是 md14 的语义：父 abort 传播给子，子 abort 不影响父）。
    """
    if parent is None:
        return

    def _waiter() -> None:
        parent.wait()
        child.set()

    t = threading.Thread(target=_waiter, daemon=True, name="subagent-abort-link")
    t.start()


def create_subagent_context(
    parent_ctx: Optional[SubagentContext],
    parent_registry: ToolRegistry,
    agent_definition: "AgentDefinition",
) -> SubagentContext:
    """参照 md14 §2.4 `createSubagentContext`。

    隔离策略（与 md14 对照表）：
    | 状态            | MyCLI 策略   | 等价 md14 描述                         |
    |-----------------|--------------|----------------------------------------|
    | abort_event     | 新建子事件   | createChildAbortController             |
    | discovered_tools| 新建空 Set   | 隔离子级的 tool_search 发现，不污染父级 |
    | parent_registry | 共享引用     | 子 registry 在 build_subagent_registry  |
    |                 |              | 中按过滤规则拷出，原 registry 不被改动  |
    | depth           | +1           | queryTracking.depth + 1                |
    """
    parent_depth = parent_ctx.depth if parent_ctx else 0
    parent_abort = parent_ctx.abort_event if parent_ctx else None

    child_abort = threading.Event()
    _link_abort(child_abort, parent_abort)

    return SubagentContext(
        agent_definition=agent_definition,
        parent_registry=parent_registry,
        depth=parent_depth + 1,
        parent=parent_ctx,
        abort_event=child_abort,
        discovered_tools=set(),  # 默认隔离
    )


# ── 工具过滤 ──

def _filter_global_disallowed(
    candidates: List[str],
    *,
    extra_disallowed: Optional[Set[str]] = None,
) -> List[str]:
    """第一层：剔除全局禁止工具（默认 = AGENT_TOOL_NAME）。

    对应 md14 §三第一层 ALL_AGENT_DISALLOWED_TOOLS。MyCLI 没有 mcp__ 前缀
    无条件放行的需求（因为我们的 MCP 工具是直接注册到 registry 的普通 Tool
    实例，没有用前缀做硬编码穿透）。
    """
    blocked = set(ALL_AGENT_DISALLOWED_TOOLS)
    if extra_disallowed:
        blocked |= extra_disallowed
    return [n for n in candidates if n not in blocked]


def _filter_definition_level(
    candidates: List[str],
    definition: "AgentDefinition",
) -> List[str]:
    """第二/三层：应用 AgentDefinition 的 tools 白名单与 disallowed_tools 黑名单。

    对应 md14 §3.1 `resolveAgentTools` 第三层。
    """
    # 先剪 disallowed（黑名单永远生效）
    if definition.disallowed_tools:
        blocked = set(definition.disallowed_tools)
        candidates = [n for n in candidates if n not in blocked]

    # 再用 tools 白名单收敛（除非通配）
    if not definition.is_wildcard_tools:
        allowed = set(definition.tools or [])
        candidates = [n for n in candidates if n in allowed]

    return candidates


def build_subagent_registry(
    parent_registry: ToolRegistry,
    definition: "AgentDefinition",
) -> ToolRegistry:
    """根据三层过滤规则，构造一个仅供子 Agent 使用的 ToolRegistry。

    实现要点：
    - 不修改父 registry（深隔离）；新建空 registry 然后选择性拷入。
    - 拷贝时同时复制 `always_visible` 与 search_hint，确保 tool_search 行为
      在子 Agent 里保持一致。
    - **不**拷 AGENT_TOOL_NAME —— 即默认子 Agent 内不能再派遣子 Agent（与
      md14 ALL_AGENT_DISALLOWED_TOOLS 一致），这正是 MAX_AGENT_DEPTH=1
      的双保险。
    """
    sub = ToolRegistry()

    # 收集父 registry 已知的所有工具名（含懒加载）
    all_names = [m["name"] for m in parent_registry.list_all_meta()]

    # 三层过滤
    names = _filter_global_disallowed(all_names)
    names = _filter_definition_level(names, definition)

    # 把过滤后的工具/懒条目拷入子 registry
    name_set = set(names)
    for name, tool in parent_registry._tools.items():  # noqa: SLF001 - 受信内部访问
        if name not in name_set:
            continue
        sub._tools[name] = tool  # noqa: SLF001
    for name, entry in parent_registry._lazy.items():  # noqa: SLF001
        if name not in name_set:
            continue
        sub._lazy[name] = entry  # noqa: SLF001

    return sub
