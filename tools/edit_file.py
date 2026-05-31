"""文件编辑工具：精确替换文件中的某段内容。"""

from __future__ import annotations

import os
from typing import Any, Dict, List

from tools.base import Tool, ToolParameter


class EditFileTool(Tool):
    """在文件中精确替换一段文本（old_str → new_str）。"""

    def __init__(self) -> None:
        super().__init__(
            name="edit_file",
            description=(
                "对文件做精确的字符串替换：将 old_str 替换为 new_str。"
                "old_str 必须在文件中唯一出现；若有多处匹配，操作会被拒绝以防误改。"
                "适合修改代码、配置文件中的特定片段，比重写整个文件更安全。"
            ),
            expandable=False,
        )

    def get_parameters(self) -> List[ToolParameter]:
        return [
            ToolParameter(
                name="path",
                type="string",
                description="要编辑的文件路径。",
                required=True,
            ),
            ToolParameter(
                name="old_str",
                type="string",
                description="要被替换的原始文本（必须在文件中唯一出现）。",
                required=True,
            ),
            ToolParameter(
                name="new_str",
                type="string",
                description="替换后的新文本。",
                required=True,
            ),
        ]

    def run(self, parameters: Dict[str, Any]) -> str:
        path = str(parameters.get("path", "")).strip()
        old_str = str(parameters.get("old_str", ""))
        new_str = str(parameters.get("new_str", ""))

        if not path:
            return "path 不能为空。"
        if not old_str:
            return "old_str 不能为空。"

        abs_path = os.path.abspath(path)
        if not os.path.isfile(abs_path):
            return f"文件不存在: {abs_path}"

        try:
            with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
                original = f.read()
        except OSError as e:
            return f"读取文件失败: {e}"

        count = original.count(old_str)
        if count == 0:
            return f"未在文件中找到 old_str，未做任何修改。\n请检查空格、换行或缩进是否完全一致。"
        if count > 1:
            return (
                f"old_str 在文件中出现了 {count} 次，操作已拒绝。\n"
                "请提供更多上下文，使 old_str 在文件中唯一匹配。"
            )

        updated = original.replace(old_str, new_str, 1)
        try:
            with open(abs_path, "w", encoding="utf-8") as f:
                f.write(updated)
        except OSError as e:
            return f"写入失败: {e}"

        old_lines = old_str.count("\n") + 1
        new_lines = new_str.count("\n") + 1
        return (
            f"已编辑 {abs_path}："
            f"替换了 {old_lines} 行 → {new_lines} 行"
        )
