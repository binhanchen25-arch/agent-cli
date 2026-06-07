"""AgentDefinition — 子 Agent 的数据蓝图。

对应 md14 §一 `BaseAgentDefinition`。MyCLI 删掉了与 React/AppState/MCP/Plugin
相关的字段（`hooks` / `mcpServers` / `permissionMode` / `criticalSystemReminder`
等），只保留对终端 ReAct 流程真正有意义的配置：
工具收敛、System Prompt、模型、最大轮次、是否继承父级历史。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass(frozen=True)
class AgentDefinition:
    """子 Agent 配置蓝图（不可变）。"""

    # 唯一标识，例如 "explore" / "plan" / "general-purpose"
    agent_type: str

    # 一句话能力描述，会被 AgentTool 的 description 引用，给主 Agent 看
    description: str

    # 何时该派遣这个子 Agent —— 帮助主 Agent 在多个 agent_type 之间做选择
    when_to_use: str

    # 子 Agent 的 system prompt（完全独立于父 Agent）
    system_prompt: str

    # 工具白名单：None 或 ["*"] 表示「父级 registry 中除全局禁止外全部可用」
    tools: Optional[List[str]] = None

    # 工具黑名单：相对父级 registry 再裁一刀
    disallowed_tools: List[str] = field(default_factory=list)

    # 模型覆盖：None 表示继承父级 config.model
    model: Optional[str] = None

    # 子 Agent 最大对话轮次（防止失控）
    max_steps: int = 15

    # 是否继承父 Agent 的对话历史。默认 False = Fresh 模式（独立上下文，
    # 不污染主对话；这是 md14 中 Explore/Plan 的默认形态）。
    # True = Fork 模式（带着父对话出发；MyCLI 暂不优化 prompt-cache，
    # 仅做"看得见父级讨论"用）。
    inherit_history: bool = False

    def __post_init__(self) -> None:
        if not self.agent_type:
            raise ValueError("AgentDefinition.agent_type 不能为空")
        if not self.system_prompt:
            raise ValueError(
                f"AgentDefinition({self.agent_type}).system_prompt 不能为空"
            )
        if self.max_steps <= 0:
            raise ValueError(
                f"AgentDefinition({self.agent_type}).max_steps 必须为正整数"
            )

    @property
    def is_wildcard_tools(self) -> bool:
        """tools 字段是否表示"全部可用"。"""
        if self.tools is None:
            return True
        if len(self.tools) == 1 and self.tools[0] == "*":
            return True
        return False
