"""工具注册表：与 ReAct 的 `工具名[原始参数串]` 格式对接。"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from tools.base import Tool


class ToolRegistry:
    """登记 `Tool` 实例；执行时把方括号内字符串解析为参数字典。"""

    def __init__(self) -> None:
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.expandable:
            expanded = tool.get_expanded_tools()
            if expanded:
                for t in expanded:
                    self._tools[t.name] = t
                return
        self._tools[tool.name] = tool

    def register_many(self, tools: List[Tool]) -> None:
        for t in tools:
            self.register(t)

    def get_tool(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def get_tools_description(self) -> str:
        if not self._tools:
            return "（当前未注册任何工具）"
        lines: List[str] = []
        for t in self._tools.values():
            params = t.get_parameters()
            if not params:
                lines.append(f"- **{t.name}**: {t.description}")
                continue
            plist = []
            for p in params:
                req = "必填" if p.required else "可选"
                plist.append(f"`{p.name}` ({p.type}, {req}): {p.description}")
            lines.append(f"- **{t.name}**: {t.description}\n  参数: " + "；".join(plist))
        return "\n".join(lines)

    def _raw_to_params(self, tool: Tool, raw_input: str) -> Dict[str, Any]:
        params_def = tool.get_parameters()
        if not params_def:
            return {}
        if len(params_def) == 1:
            p0 = params_def[0]
            return {p0.name: raw_input}
        stripped = raw_input.strip()
        if stripped.startswith("{"):
            try:
                data = json.loads(stripped)
            except json.JSONDecodeError:
                return {}
            if isinstance(data, dict):
                return data
            return {}
        return {}

    def execute_tool(self, name: str, raw_input: str) -> str:
        tool = self._tools.get(name)
        if not tool:
            return f"未知工具: {name}。请从可用工具中选择。"

        parameters = self._raw_to_params(tool, raw_input)
        if not tool.validate_parameters(parameters):
            needed = [p.name for p in tool.get_parameters() if p.required]
            return (
                f"参数不完整。工具 `{name}` 需要字段: {needed}。"
                "多参数时请在大括号内传入 JSON，例如: mytool[{\"key\": \"value\"}]"
            )
        try:
            return tool.run(parameters)
        except Exception as e:
            return f"工具执行错误: {e}"
