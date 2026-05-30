"""SDK 内部数据类型 —— 对应 Claude Code 的 ``sdk/coreTypes.ts``。

把 ``core.llm`` 中的运行时数据类（``LLMResponse`` / ``ToolCall``）
集中 re-export，让外部门面 ``entrypoints.sdk_types`` 不直接依赖 ``core/``。
"""

from __future__ import annotations

from core.llm import LLMResponse, ToolCall

__all__ = ["LLMResponse", "ToolCall"]
