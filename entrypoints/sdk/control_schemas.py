"""SDK 控制层 schema —— 对应 Claude Code 的 ``sdk/controlSchemas.ts``。

定义外部调用方在发起一次 ``query()`` 时可以传入的可选配置。
保持纯 Pydantic 模型，便于外部用户直接构造、序列化或在 IDE 中获得补全。
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class QueryOptions(BaseModel):
    """一次性 ``query()`` 调用的可选配置。"""

    model_config = ConfigDict(extra="forbid")

    max_steps: int = Field(default=20, ge=1, le=100, description="ReAct 循环最大步数")
    system_prompt: Optional[str] = Field(default=None, description="覆盖默认的 agent 系统提示词")
    allow_all_commands: bool = Field(
        default=False,
        description="若为 True，则 windows_cmd 工具跳过人工确认。等价于 REPL 中的 \\allow",
    )


__all__ = ["QueryOptions"]
