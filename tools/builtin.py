"""内置示例工具（可直接用于 ReAct 演示）。"""

from __future__ import annotations

import fnmatch
import os
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from rich.panel import Panel

from cli.renderer import console
from tools.base import Tool, ToolParameter, UserRefusedError
from tools.registry import ToolRegistry

_ALLOW_ALL_WINDOWS_CMD = False


def set_allow_all_windows_cmd(enabled: bool) -> None:
    """设置是否跳过 windows_cmd 的人工确认。"""
    global _ALLOW_ALL_WINDOWS_CMD
    _ALLOW_ALL_WINDOWS_CMD = enabled


def get_allow_all_windows_cmd() -> bool:
    """读取是否跳过 windows_cmd 的人工确认。"""
    return _ALLOW_ALL_WINDOWS_CMD


def _confirm_in_cli(command: str) -> bool:
    """纯命令行确认：输入 yes/y 执行，no/n 取消。"""
    while True:
        answer = console.input(
            f"[bold yellow]确认执行该命令？[/bold yellow] 输入 [green]yes/y[/green] 或 [red]no/n[/red]\n> "
        ).strip().lower()
        if answer in ("yes", "y"):
            return True
        if answer in ("no", "n"):
            return False
        console.print("请输入 yes/y 或 no/n。", style="error")


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
                "每次执行前会在 CLI 显示确认提示并要求输入 yes/no；"
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
            approved = _confirm_in_cli(command)
            if not approved:
                raise UserRefusedError("windows_cmd", f"用户拒绝执行命令: {command}")

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


class TreeTool(Tool):
    """列出目录结构树。"""

    def __init__(self) -> None:
        super().__init__(
            name="tree",
            description="列出指定目录的文件结构树。参数为目录路径，可选用 | 分隔最大深度，如 ./src|3。默认深度 2。",
            expandable=False,
        )

    def get_parameters(self) -> List[ToolParameter]:
        return [
            ToolParameter(name="input", type="string", description="目录路径，可用 | 分隔深度，如 ./src|3", required=True),
        ]

    def run(self, parameters: Dict[str, Any]) -> str:
        raw = str(parameters.get("input", ".")).strip()
        parts = raw.split("|", 1)
        directory = parts[0].strip() or "."
        max_depth = 2
        if len(parts) > 1:
            try:
                max_depth = int(parts[1].strip())
            except ValueError:
                pass

        directory = os.path.abspath(directory)
        if not os.path.isdir(directory):
            return f"目录不存在: {directory}"

        lines: List[str] = [directory]
        max_items = 500

        def _walk(dir_path: str, prefix: str, depth: int):
            nonlocal max_items
            if depth > max_depth or max_items <= 0:
                return
            try:
                entries = sorted(os.listdir(dir_path))
            except PermissionError:
                lines.append(f"{prefix}[权限不足]")
                return

            # 过滤隐藏文件和常见无关目录
            skip = {".git", "__pycache__", "node_modules", ".venv", ".idea", ".DS_Store"}
            entries = [e for e in entries if e not in skip]

            for i, name in enumerate(entries):
                if max_items <= 0:
                    lines.append(f"{prefix}... (已截断)")
                    return
                max_items -= 1
                full = os.path.join(dir_path, name)
                is_last = (i == len(entries) - 1)
                connector = "└── " if is_last else "├── "
                if os.path.isdir(full):
                    lines.append(f"{prefix}{connector}{name}/")
                    extension = "    " if is_last else "│   "
                    _walk(full, prefix + extension, depth + 1)
                else:
                    lines.append(f"{prefix}{connector}{name}")

        _walk(directory, "", 1)
        return "\n".join(lines)


class GlobTool(Tool):
    """按模式匹配查找文件。"""

    def __init__(self) -> None:
        super().__init__(
            name="glob",
            description="按 glob 模式查找文件。参数为 pattern，如 **/*.py 或 src/**/*.js。在当前目录下搜索。",
            expandable=False,
        )

    def get_parameters(self) -> List[ToolParameter]:
        return [
            ToolParameter(name="pattern", type="string", description="glob 模式，如 **/*.py", required=True),
        ]

    def run(self, parameters: Dict[str, Any]) -> str:
        pattern = str(parameters.get("pattern", "")).strip()
        if not pattern:
            return "请提供 glob 模式，如 **/*.py"

        base = Path(".")
        matches = sorted(str(p) for p in base.glob(pattern) if not any(
            part.startswith(".") or part in ("__pycache__", "node_modules")
            for part in p.parts
        ))

        if not matches:
            return f"未找到匹配 `{pattern}` 的文件"

        limit = 50
        result = matches[:limit]
        out = "\n".join(result)
        if len(matches) > limit:
            out += f"\n... 共 {len(matches)} 个结果，仅显示前 {limit} 个"
        return out


class GrepTool(Tool):
    """在文件中搜索文本内容。"""

    def __init__(self) -> None:
        super().__init__(
            name="grep",
            description=(
                "在文件中搜索文本或正则表达式。"
                "参数格式: 搜索词 或 搜索词|glob模式，如 import|**/*.py。"
                "返回匹配的文件名和行号。"
            ),
            expandable=False,
        )

    def get_parameters(self) -> List[ToolParameter]:
        return [
            ToolParameter(name="input", type="string", description="搜索词，可用 | 分隔 glob 过滤，如 import|**/*.py", required=True),
        ]

    def run(self, parameters: Dict[str, Any]) -> str:
        raw = str(parameters.get("input", "")).strip()
        if not raw:
            return "请提供搜索关键词"

        parts = raw.split("|", 1)
        keyword = parts[0].strip()
        file_pattern = parts[1].strip() if len(parts) > 1 else "**/*"

        if not keyword:
            return "搜索关键词不能为空"

        try:
            pattern = re.compile(keyword, re.IGNORECASE)
        except re.error:
            pattern = re.compile(re.escape(keyword), re.IGNORECASE)

        base = Path(".")
        skip_dirs = {".git", "__pycache__", "node_modules", ".venv", ".idea"}
        results: List[str] = []
        max_results = 30

        for filepath in sorted(base.glob(file_pattern)):
            if len(results) >= max_results:
                break
            if not filepath.is_file():
                continue
            if any(part in skip_dirs for part in filepath.parts):
                continue
            try:
                text = filepath.read_text(encoding="utf-8", errors="ignore")
                for line_num, line in enumerate(text.splitlines(), 1):
                    if pattern.search(line):
                        results.append(f"{filepath}:{line_num}: {line.strip()[:120]}")
                        if len(results) >= max_results:
                            break
            except (OSError, UnicodeDecodeError):
                continue

        if not results:
            return f"未找到匹配 `{keyword}` 的内容"

        out = "\n".join(results)
        if len(results) >= max_results:
            out += f"\n... 结果已截断（最多 {max_results} 条）"
        return out


class ViewTool(Tool):
    """查看文件内容（支持行范围）。"""

    def __init__(self) -> None:
        super().__init__(
            name="view",
            description=(
                "查看文件内容。参数为文件路径，可用 | 指定行范围，如 main.py|1-30。"
                "不指定范围则返回前 200 行。"
            ),
            expandable=False,
        )

    def get_parameters(self) -> List[ToolParameter]:
        return [
            ToolParameter(name="input", type="string", description="文件路径，可用 | 分隔行范围，如 src/main.py|10-50", required=True),
        ]

    def run(self, parameters: Dict[str, Any]) -> str:
        raw = str(parameters.get("input", "")).strip()
        if not raw:
            return "请提供文件路径"

        parts = raw.split("|", 1)
        filepath = parts[0].strip()
        start_line, end_line = 1, 200

        if len(parts) > 1:
            range_str = parts[1].strip()
            m = re.match(r"(\d+)\s*-\s*(\d+)", range_str)
            if m:
                start_line = max(1, int(m.group(1)))
                end_line = int(m.group(2))
            else:
                try:
                    start_line = max(1, int(range_str))
                    end_line = start_line + 199
                except ValueError:
                    pass

        if not os.path.isfile(filepath):
            return f"文件不存在: {filepath}"

        try:
            with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                all_lines = f.readlines()
        except OSError as e:
            return f"读取失败: {e}"

        total = len(all_lines)
        end_line = min(end_line, total)

        if start_line > total:
            return f"文件共 {total} 行，起始行 {start_line} 超出范围"

        selected = all_lines[start_line - 1 : end_line]
        numbered = [f"{start_line + i:4d} | {line.rstrip()}" for i, line in enumerate(selected)]
        header = f"📄 {filepath}  (行 {start_line}-{end_line}，共 {total} 行)"
        return header + "\n" + "\n".join(numbered)


def default_tool_registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register_many([
        EchoTool(), NowTool(), WindowsCmdTool(),
        TreeTool(), GlobTool(), GrepTool(), ViewTool(),
    ])
    return reg
