import sys
import os
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.live import Live
from rich.spinner import Spinner
from rich.text import Text
from rich.theme import Theme
from typing import Generator

custom_theme = Theme({
    "user": "bold cyan",
    "assistant": "bold green",
    "system": "bold yellow",
    "error": "bold red",
})

console = Console(theme=custom_theme)

APP_TITLE = "🤖 MyCLI - 终端 AI 助手"


def set_terminal_title(title: str):
    """设置终端窗口标题"""
    if os.name == "nt":
        os.system(f"title {title}")
    else:
        sys.stdout.write(f"\033]0;{title}\007")
        sys.stdout.flush()


def enter_fullscreen():
    """清屏 + 隐藏光标滚动历史，只显示我们的内容"""
    if os.name == "nt":
        os.system("cls")
    else:
        # 进入备用屏幕缓冲区（和 vim/less 一样，退出后恢复原终端内容）
        sys.stdout.write("\033[?1049h\033[H\033[2J")
        sys.stdout.flush()


def exit_fullscreen():
    """退出时恢复终端"""
    if os.name != "nt":
        sys.stdout.write("\033[?1049l")
        sys.stdout.flush()


def print_welcome():
    set_terminal_title(APP_TITLE)
    enter_fullscreen()
    welcome = """
╔══════════════════════════════════════════╗
║        🤖  MyCLI - 终端 AI 助手         ║
║                                          ║
║  输入问题开始对话，输入 /help 查看帮助   ║
║  按 Ctrl+C 或输入 /exit 退出            ║
╚══════════════════════════════════════════╝"""
    console.print(welcome, style="bold blue")
    console.print()


def print_user_message(text: str):
    console.print()
    console.print(Text("  ❯ ", style="user"), end="")
    console.print(text, style="bold white")


def render_stream(stream: Generator[str, None, None]) -> str:
    """流式渲染 Markdown，返回完整文本"""
    full_text = ""
    console.print()
    with Live(console=console, refresh_per_second=12, vertical_overflow="visible") as live:
        for chunk in stream:
            full_text += chunk
            live.update(
                Panel(
                    Markdown(full_text),
                    border_style="green",
                    title="🤖 助手",
                    title_align="left",
                    padding=(0, 1),
                )
            )
    return full_text


def print_system(text: str):
    console.print(f"\n  💡 {text}", style="system")


def print_error(text: str):
    console.print(f"\n  ❌ {text}", style="error")


def print_config(config: dict):
    from rich.table import Table

    table = Table(title="⚙️  当前配置", border_style="blue")
    table.add_column("配置项", style="cyan")
    table.add_column("值", style="white")

    display_config = config.copy()
    if display_config.get("api_key"):
        key = display_config["api_key"]
        display_config["api_key"] = key[:8] + "..." + key[-4:] if len(key) > 12 else "***"
    else:
        display_config["api_key"] = "(未设置)"

    for k, v in display_config.items():
        table.add_row(k, str(v))

    console.print()
    console.print(table)


def clear_screen():
    enter_fullscreen()
    welcome = """
╔══════════════════════════════════════════╗
║        🤖  MyCLI - 终端 AI 助手         ║
║                                          ║
║  输入问题开始对话，输入 /help 查看帮助   ║
║  按 Ctrl+C 或输入 /exit 退出            ║
╚══════════════════════════════════════════╝"""
    console.print(welcome, style="bold blue")
    console.print()
