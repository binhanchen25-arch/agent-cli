"""文件操作工具：复制、移动、删除、重命名文件或目录。"""

from __future__ import annotations

import os
import shutil
from typing import Any, Dict, List

from tools.base import Tool, ToolParameter


class FileOpsTool(Tool):
    """对文件或目录执行 copy / move / delete / rename 操作。"""

    def __init__(self) -> None:
        super().__init__(
            name="file_ops",
            description=(
                "对文件或目录执行操作，支持四种 action：\n"
                "- copy：将 src 复制到 dst\n"
                "- move：将 src 移动（或重命名）到 dst\n"
                "- delete：删除 src（文件或目录，目录会递归删除）\n"
                "- rename：将 src 重命名为 dst（同目录下改名）"
            ),
            expandable=False,
        )

    def get_parameters(self) -> List[ToolParameter]:
        return [
            ToolParameter(
                name="action",
                type="string",
                description="操作类型：copy | move | delete | rename",
                required=True,
            ),
            ToolParameter(
                name="src",
                type="string",
                description="源文件或目录路径。",
                required=True,
            ),
            ToolParameter(
                name="dst",
                type="string",
                description="目标路径（delete 操作时可省略）。",
                required=False,
            ),
        ]

    def run(self, parameters: Dict[str, Any]) -> str:
        action = str(parameters.get("action", "")).strip().lower()
        src = str(parameters.get("src", "")).strip()
        dst = str(parameters.get("dst", "")).strip()

        if not action:
            return "action 不能为空，支持：copy | move | delete | rename"
        if not src:
            return "src 不能为空。"

        abs_src = os.path.abspath(src)

        if action == "delete":
            if not os.path.exists(abs_src):
                return f"路径不存在: {abs_src}"
            try:
                if os.path.isdir(abs_src):
                    shutil.rmtree(abs_src)
                    return f"已删除目录: {abs_src}"
                else:
                    os.remove(abs_src)
                    return f"已删除文件: {abs_src}"
            except OSError as e:
                return f"删除失败: {e}"

        if not dst:
            return f"action={action} 需要提供 dst 参数。"

        abs_dst = os.path.abspath(dst)

        if action == "copy":
            if not os.path.exists(abs_src):
                return f"源路径不存在: {abs_src}"
            try:
                if os.path.isdir(abs_src):
                    shutil.copytree(abs_src, abs_dst)
                    return f"已复制目录: {abs_src} → {abs_dst}"
                else:
                    os.makedirs(os.path.dirname(abs_dst), exist_ok=True)
                    shutil.copy2(abs_src, abs_dst)
                    return f"已复制文件: {abs_src} → {abs_dst}"
            except OSError as e:
                return f"复制失败: {e}"

        if action in ("move", "rename"):
            if not os.path.exists(abs_src):
                return f"源路径不存在: {abs_src}"
            try:
                os.makedirs(os.path.dirname(abs_dst) or ".", exist_ok=True)
                shutil.move(abs_src, abs_dst)
                verb = "重命名" if action == "rename" else "移动"
                return f"已{verb}: {abs_src} → {abs_dst}"
            except OSError as e:
                return f"操作失败: {e}"

        return f"未知 action: {action}，支持：copy | move | delete | rename"
