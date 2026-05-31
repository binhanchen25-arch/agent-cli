"""工具执行确认：统一的 allow 开关与 CLI 确认输入。"""

from __future__ import annotations

from cli.renderer import console

_ALLOW_ALL_WINDOWS_CMD = False


def set_allow_all_windows_cmd(enabled: bool) -> None:
    """设置是否跳过危险工具的人工确认。"""
    global _ALLOW_ALL_WINDOWS_CMD
    _ALLOW_ALL_WINDOWS_CMD = enabled


def get_allow_all_windows_cmd() -> bool:
    """读取是否跳过危险工具的人工确认。"""
    return _ALLOW_ALL_WINDOWS_CMD


def confirm_in_cli(detail: str) -> bool:
    """纯命令行确认：输入 yes/y 执行，no/n 取消。"""
    while True:
        answer = console.input(
            f"[bold yellow]确认执行该操作？[/bold yellow]\\n{detail}\\n"
            "输入 [green]yes/y[/green] 或 [red]no/n[/red]\\n> "
        ).strip().lower()
        if answer in ("yes", "y"):
            return True
        if answer in ("no", "n"):
            return False
        console.print("请输入 yes/y 或 no/n。", style="error")
