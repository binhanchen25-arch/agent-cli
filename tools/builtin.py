"""内置示例工具（可直接用于 ReAct 演示）。"""

from __future__ import annotations

import os
import shutil
import subprocess
from datetime import datetime
from typing import Any, Dict, List

from prompt_toolkit.shortcuts import button_dialog
from rich.panel import Panel

from cli.renderer import console
from tools.base import Tool, ToolParameter
from tools.registry import ToolRegistry

_ALLOW_ALL_WINDOWS_CMD = False


def set_allow_all_windows_cmd(enabled: bool) -> None:
    """设置是否跳过 windows_cmd 的人工确认。"""
    global _ALLOW_ALL_WINDOWS_CMD
    _ALLOW_ALL_WINDOWS_CMD = enabled


def get_allow_all_windows_cmd() -> bool:
    """读取是否跳过 windows_cmd 的人工确认。"""
    return _ALLOW_ALL_WINDOWS_CMD


class EchoTool(Tool):
    """原样返回输入文本。"""

    def __init__(self) -> None:
        super().__init__(
            name="echo",
            description="原样返回传入的文本，用于确认或回显信息。",
            expandable=False,
        )

    def get_parameters(self) -> List[ToolParameter]:
        return [
            ToolParameter(
                name="text",
                type="string",
                description="要回显的文本。",
                required=True,
            )
        ]

    def run(self, parameters: Dict[str, Any]) -> str:
        return str(parameters.get("text", ""))


class NowTool(Tool):
    """返回当前本地时间。"""

    def __init__(self) -> None:
        super().__init__(
            name="now",
            description="返回当前本地时间（ISO 8601 字符串）。调用时使用 now[] 或 now[任意占位] 均可。",
            expandable=False,
        )

    def get_parameters(self) -> List[ToolParameter]:
        return []

    def run(self, parameters: Dict[str, Any]) -> str:
        return datetime.now().isoformat(timespec="seconds")


class WindowsCmdTool(Tool):
    """跨平台执行命令（执行前要求用户确认）。"""

    def __init__(self) -> None:
        super().__init__(
            name="windows_cmd",
            description=(
                "在本机终端执行命令：Windows 使用 cmd.exe，macOS/Linux 使用 bash。"
                "每次执行前会在 CLI 渲染确认框并提供 Yes/No 按钮；"
                "若用户执行 `/allow all`，则跳过确认直接执行。"
            ),
            expandable=False,
        )

    def get_parameters(self) -> List[ToolParameter]:
        return [
            ToolParameter(
                name="command",
                type="string",
                description="要执行的命令文本（Windows 用 cmd 语法，macOS/Linux 用 bash 语法）。",
                required=True,
            )
        ]

    def run(self, parameters: Dict[str, Any]) -> str:
        command = str(parameters.get("command", "")).strip()
        if not command:
            return "命令为空，未执行。"

        if os.name == "nt":
            runner = ["cmd", "/c", command]
            shell_name = "Windows CMD"
        else:
            shell_bin = shutil.which("bash") or shutil.which("sh")
            if not shell_bin:
                return "当前系统未找到 bash/sh，无法执行命令。"
            runner = [shell_bin, "-lc", command]
            shell_name = os.path.basename(shell_bin)

        console.print(
            Panel(
                f"[bold]准备执行命令：[/bold]\n{command}",
                title=f"⚠️ 命令执行确认 ({shell_name})",
                border_style="yellow",
                padding=(1, 2),
            )
        )

        if not get_allow_all_windows_cmd():
            approved = button_dialog(
                title="命令执行确认",
                text=f"将要执行以下命令：\n\n{command}\n\n是否继续？",
                buttons=[("Yes", True), ("No", False)],
            ).run()
            if not approved:
                return "用户拒绝执行命令。"

        try:
            completed = subprocess.run(
                runner,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
                shell=False,
            )
        except subprocess.TimeoutExpired:
            return "命令执行超时（60 秒）。"
        except Exception as exc:
            return f"命令执行失败: {exc}"

        stdout = (completed.stdout or "").strip()
        stderr = (completed.stderr or "").strip()
        if not stdout:
            stdout = "(无输出)"
        if not stderr:
            stderr = "(无错误输出)"
        return f"exit_code={completed.returncode}\nstdout:\n{stdout}\nstderr:\n{stderr}"


def default_tool_registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register_many([EchoTool(), NowTool(), WindowsCmdTool()])
    return reg
