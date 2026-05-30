"""SDK 公共参数 schema —— 对应 Claude Code 的 ``sdk/coreSchemas.ts``。

re-export ``ToolParameter``，让 SDK 用户用一个稳定的导入路径定义自定义工具参数。
"""

from __future__ import annotations

from tools.base import ToolParameter

__all__ = ["ToolParameter"]
