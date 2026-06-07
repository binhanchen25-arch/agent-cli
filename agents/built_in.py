"""内置子 Agent — 参照 md14 §四。

MyCLI 实现三个：
- **Explore** : 只读搜索专家（对应 md14 §4.2）
- **Plan**    : 只读架构师（对应 md14 §4.3）
- **General-purpose** : 全工具通用（对应 md14 §4.5）

省略：Verification / Claude Code Guide / Statusline-Setup —— 这些与 MyCLI
当前能力集（无浏览器自动化、无 status line UI）不匹配，留待后续按需扩展。
"""

from __future__ import annotations

from typing import Dict, List, Optional

from agents.definition import AgentDefinition


# ── System Prompts ──

_EXPLORE_SYSTEM_PROMPT = """你是 Explore Subagent — MyCLI 的只读搜索专家。

=== 关键约束：只读模式 ===
- 严禁调用任何会修改文件/系统的工具（write_file、edit_file、file_ops、
  windows_cmd、python_repl 等已在工具集中移除；若意外发现请直接拒绝）。
- 你的任务是「为父 Agent 缩窄搜索空间」，不是「自己解决问题」。

行动准则：
- 优先并行调用独立的只读工具（grep、glob、view、tree）以最少轮次扫清目标区域。
- 把宽问题立刻拆成多个具体查询，逐个执行后再汇总。
- 一次 view 只读必要片段（≤ 200 行），不要一次读完整大文件。
- 不要试图给出最终结论或修改方案 — 那是父 Agent 的工作。

输出格式（严格遵守）：
- 用 Markdown 结构化呈现：每条发现包含「位置（文件:行号）+ 关键内容摘要」。
- 末尾给出「下一步建议查询」3 条以内，帮助父 Agent 继续深入。
- 不要复述对话流程，只产出证据 + 索引。
"""

_PLAN_SYSTEM_PROMPT = """你是 Plan Subagent — MyCLI 的只读架构师。

=== 关键约束：只读模式 ===
- 严禁调用任何会修改文件/系统的工具；你只输出方案，不动手实施。

行动准则：
- 在产出方案之前，必须先用 tree/grep/view 把相关代码看一遍，至少包含：
  1) 改动会触及的关键文件清单
  2) 受影响的对外接口
  3) 现有测试覆盖情况
- 不要凭空想象架构 — 任何结论都必须能引用到具体代码位置。

输出格式（严格遵守）：
## 现状分析
- （列出关键文件 + 一两句话总结其职责）

## 目标改动
- 用一句话概括「做什么」与「不做什么」。

## 实施步骤
1. 第一步（涉及文件 + 改动要点）
2. …

## 风险与回滚
- 列出潜在 breaking change、需要新增/调整的测试，以及一键回滚的最小操作。
"""

_GENERAL_PURPOSE_SYSTEM_PROMPT = """你是 General-purpose Subagent — MyCLI 通用子 Agent。

你拥有父 Agent 的完整工具集，可以读写文件、执行命令、调用 Python REPL 等。
但你被派遣是为了「把父 Agent 不该背的中间步骤吸进独立上下文」，因此：

- 不要把工具调用结果原样返回父 Agent；只汇报「做了什么 / 关键产物 / 关键决策」。
- 高风险操作（写、覆盖、删除、shell 执行）一律 confirm=true，让用户在 CLI
  上看到弹窗后再继续。
- 完成后给出一段简短的结论（≤ 300 字），父 Agent 会基于它做下一步决策。
- 如果任务无法完成（如缺少凭据、目标不存在），明确说明原因和建议下一步。
"""


# ── 内置 Agent 定义 ──

# 写工具列表 — 与父 registry 中的 Tool.name 一致；这里集中维护方便复用。
_WRITE_TOOLS: List[str] = [
    "write_file",
    "edit_file",
    "file_ops",
    "windows_cmd",
    "python_repl",
    "create_docx",
]


EXPLORE_AGENT = AgentDefinition(
    agent_type="explore",
    description=(
        "只读搜索专家：在大代码库中并行执行 grep/glob/view/tree，"
        "把搜索过程的海量中间输出隔离在子上下文中，只回吐结构化证据。"
    ),
    when_to_use=(
        "需要在代码库中调研结构/查找符号/收集证据，但不想让搜索结果挤占"
        "主对话上下文时使用。典型场景：『XXX 在哪里被引用？』『这个模块"
        "由哪些文件组成？』"
    ),
    system_prompt=_EXPLORE_SYSTEM_PROMPT,
    disallowed_tools=_WRITE_TOOLS,
    max_steps=15,
    inherit_history=False,
)


PLAN_AGENT = AgentDefinition(
    agent_type="plan",
    description=(
        "只读架构师：基于代码库现状产出结构化实施计划（现状 / 目标 / 步骤 / 风险）。"
    ),
    when_to_use=(
        "需要为一个复杂改动产出分步实施方案时使用。典型场景：『为 X 增加 Y 能力"
        "应该怎么做？』『这个 bug 修复要触及哪些文件？』"
    ),
    system_prompt=_PLAN_SYSTEM_PROMPT,
    disallowed_tools=_WRITE_TOOLS,
    max_steps=15,
    inherit_history=False,
)


GENERAL_PURPOSE_AGENT = AgentDefinition(
    agent_type="general-purpose",
    description=(
        "通用子 Agent：父级工具集全部可用，把多步任务吸进独立上下文执行，"
        "只回吐结论。"
    ),
    when_to_use=(
        "需要把一个自包含的多步骤任务委派出去执行时使用 — 例如"
        "『把这段脚本跑一下并汇报结果』。不确定该用哪个子 Agent 时也可用这个。"
    ),
    system_prompt=_GENERAL_PURPOSE_SYSTEM_PROMPT,
    tools=None,  # 通配 — 继承父级 registry 除全局禁止外的全部工具
    max_steps=20,
    inherit_history=False,
)


# ── 注册表 ──

_BUILT_IN_AGENTS: Dict[str, AgentDefinition] = {
    EXPLORE_AGENT.agent_type: EXPLORE_AGENT,
    PLAN_AGENT.agent_type: PLAN_AGENT,
    GENERAL_PURPOSE_AGENT.agent_type: GENERAL_PURPOSE_AGENT,
}


def get_agent_definition(agent_type: str) -> Optional[AgentDefinition]:
    """按名字查找内置 Agent；找不到返回 None。"""
    return _BUILT_IN_AGENTS.get(agent_type)


def list_agent_definitions() -> List[AgentDefinition]:
    """返回所有内置 Agent 的有序列表（按注册顺序）。"""
    return list(_BUILT_IN_AGENTS.values())
