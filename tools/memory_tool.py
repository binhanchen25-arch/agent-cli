"""CLI memory 工具：按 type 读取固定 memory 文件。"""

from __future__ import annotations

from typing import Any, Dict, List

from memory import MEMORY_FILE_MAP, resolve_memory_file
from tools.base import Tool, ToolParameter


class MemoryTool(Tool):
    """读取 CLI 级 memory 文件。"""

    search_hint = "读取项目记忆文件"

    def __init__(self) -> None:
        super().__init__(
            name="memory",
            description=(
                "按 type 读取 CLI 级 memory 文件。"
                "type 可用值：user_role、feedback_testing、project_auth_rewrite。"
            ),
            expandable=False,
        )

    def get_parameters(self) -> List[ToolParameter]:
        return [
            ToolParameter(
                name="type",
                type="string",
                description=(
                    "memory 文件类型："
                    "user_role | feedback_testing | project_auth_rewrite"
                ),
                required=True,
            )
        ]

    def is_read_only(self, parameters=None) -> bool:
        return True

    def is_concurrency_safe(self, parameters=None) -> bool:
        return True

    def run(self, parameters: Dict[str, Any]) -> str:
        memory_type = str(parameters.get("type", "")).strip()
        if not memory_type:
            return "type 不能为空。"

        try:
            target = resolve_memory_file(memory_type)
        except ValueError as e:
            return str(e)

        try:
            content = target.read_text(encoding="utf-8")
        except OSError as e:
            return f"读取 memory 失败: {e}"

        mapped = ", ".join(f"{k}->{v}" for k, v in MEMORY_FILE_MAP.items())
        return (
            f"memory_file: {target}\n"
            f"supported_types: {mapped}\n"
            f"---\n{content}"
        )
