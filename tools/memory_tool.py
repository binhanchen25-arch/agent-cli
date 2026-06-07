"""CLI memory 工具：按 type 读取固定 memory 文件。"""

from __future__ import annotations

from typing import Any, Dict, List

from memory import (
    MEMORY_FILE_MAP,
    append_text_with_lock,
    mark_memory_written_by_tool,
    read_text_with_lock,
    resolve_memory_file,
)
from tools.base import Tool, ToolParameter


class MemoryTool(Tool):
    """读取 CLI 级 memory 文件。"""

    search_hint = "读取项目记忆文件"

    def __init__(self) -> None:
        super().__init__(
            name="memory",
            description=(
                "按 type 读写 CLI 级 memory 文件。"
                "type 可用值：user_role、feedback_testing、project_auth_rewrite。"
                "action=read 或 write，write 时需要 content。"
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
            ),
            ToolParameter(
                name="action",
                type="string",
                description="操作类型：read（默认）或 write。",
                required=False,
                default="read",
            ),
            ToolParameter(
                name="content",
                type="string",
                description="当 action=write 时要写入的内容。",
                required=False,
            )
        ]

    def is_read_only(self, parameters=None) -> bool:
        action = str((parameters or {}).get("action", "read")).strip().lower()
        return action != "write"

    def is_concurrency_safe(self, parameters=None) -> bool:
        return True

    def run(self, parameters: Dict[str, Any]) -> str:
        memory_type = str(parameters.get("type", "")).strip()
        action = str(parameters.get("action", "read")).strip().lower()
        if not memory_type:
            return "type 不能为空。"

        try:
            target = resolve_memory_file(memory_type)
        except ValueError as e:
            return str(e)

        if action == "write":
            content_to_write = str(parameters.get("content", "")).strip()
            if not content_to_write:
                return "action=write 时 content 不能为空。"
            mark_memory_written_by_tool()
            try:
                append_text_with_lock(target, f"\n{content_to_write}\n")
            except OSError as e:
                return f"写入 memory 失败: {e}"
            return f"已写入 memory: {target}"

        if action != "read":
            return "action 仅支持 read 或 write。"

        try:
            content = read_text_with_lock(target)
        except OSError as e:
            return f"读取 memory 失败: {e}"

        mapped = ", ".join(f"{k}->{v}" for k, v in MEMORY_FILE_MAP.items())
        return (
            f"memory_file: {target}\n"
            f"supported_types: {mapped}\n"
            f"---\n{content}"
        )
