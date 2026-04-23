"""工具注册表：支持 ReAct 文本格式和 Function Calling 两种调用方式。"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from tools.base import Tool, UserRefusedError


class ToolRegistry:
    """登记 `Tool` 实例；支持文本和结构化参数两种执行方式。"""

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

    def get_openai_tools_schema(self) -> List[Dict[str, Any]]:
        """返回所有工具的 OpenAI Function Calling schema 列表。"""
        return [t.to_openai_schema() for t in self._tools.values()]

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
        """ReAct 模式：从原始字符串解析参数并执行。"""
        tool = self._tools.get(name)
        if not tool:
            return f"未知工具: {name}。请从可用工具中选择。"

        parameters = self._raw_to_params(tool, raw_input)
        return self._run_with_validation(tool, parameters)

    def execute_tool_by_params(self, name: str, parameters: Dict[str, Any]) -> str:
        """Function Calling 模式：直接接收结构化参数并执行。"""
        tool = self._tools.get(name)
        if not tool:
            return f"未知工具: {name}。可用工具: {list(self._tools.keys())}"

        return self._run_with_validation(tool, parameters)

    def _run_with_validation(self, tool: Tool, parameters: Dict[str, Any]) -> str:
        """统一的参数验证 + 执行路径。"""
        if not tool.validate_parameters(parameters):
            needed = [p.name for p in tool.get_parameters() if p.required]
            return (
                f"参数不完整。工具 `{tool.name}` 需要字段: {needed}。"
                f"收到: {list(parameters.keys())}"
            )
        try:
            return tool.run(parameters)
        except UserRefusedError:
            raise
        except Exception as e:
            return f"工具执行错误: {e}"
