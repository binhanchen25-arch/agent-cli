"""文件写入工具：创建或覆盖文件内容。"""

from __future__ import annotations

import os
from typing import Any, Dict, List

from tools.base import Tool, ToolParameter, UserRefusedError
from tools.confirm import confirm_in_cli, get_allow_all_windows_cmd


class WriteFileTool(Tool):
    """创建或覆盖写入文件内容。"""

    def __init__(self) -> None:
        super().__init__(
            name="write_file",
            description=(
                "创建新文件或覆盖已有文件的全部内容。"
                "会自动创建不存在的父目录。"
                "写入前会显示路径和字节数确认。"
            ),
            expandable=False,
        )

    def get_parameters(self) -> List[ToolParameter]:
        return [
            ToolParameter(
                name="path",
                type="string",
                description="目标文件路径，如 src/main.py 或 /tmp/output.txt。",
                required=True,
            ),
            ToolParameter(
                name="content",
                type="string",
                description="要写入的文件内容（字符串）。",
                required=True,
            ),
        ]

    def run(self, parameters: Dict[str, Any]) -> str:
        path = str(parameters.get("path", "")).strip()
        content = str(parameters.get("content", ""))

        if not path:
            return "path 不能为空。"

        abs_path = os.path.abspath(path)
        parent = os.path.dirname(abs_path)

        if not get_allow_all_windows_cmd():
            approved = confirm_in_cli(
                "工具: write_file\n"
                f"目标文件: {abs_path}\n"
                f"写入字节数: {len(content.encode('utf-8'))}"
            )
            if not approved:
                raise UserRefusedError("write_file", f"用户拒绝写入文件: {abs_path}")

        try:
            os.makedirs(parent, exist_ok=True)
            with open(abs_path, "w", encoding="utf-8") as f:
                f.write(content)
        except OSError as e:
            return f"写入失败: {e}"

        lines = content.count("\n") + 1
        size = len(content.encode("utf-8"))
        return f"已写入 {abs_path}（{lines} 行，{size} 字节）"
