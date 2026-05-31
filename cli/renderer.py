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
║  输入问题开始对话，输入 \help 查看帮助   ║
║  按 Ctrl+C 或输入 \exit 退出            ║
╚══════════════════════════════════════════╝"""
    console.print(welcome, style="bold blue")
    console.print()


def print_user_message(text: str):
    console.print()
    console.print(Text("  ❯ ", style="user"), end="")
    console.print(text, style="bold white")


def render_stream(stream: Generator[str, None, None]) -> str:
    """
    流式渲染 Markdown，返回完整文本。
    Ctrl+C 时：关闭底层生成器（触发其 finally 清理）、定格已显示内容、
    在末尾追加「[已取消]」提示，并把累积的 partial 文本返回给调用方。
    """
    full_text = ""
    console.print()
    cancelled = False
    try:
        with Live(console=console, refresh_per_second=12, vertical_overflow="visible") as live:
            try:
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
            except KeyboardInterrupt:
                cancelled = True
                # 关闭生成器 → 触发 stream 内 try/finally 清理 HTTP 连接、status spinner 等
                close = getattr(stream, "close", None)
                if callable(close):
                    try:
                        close()
                    except Exception:
                        pass
                # 在已显示内容末尾追加取消标记并定格
                full_text_with_mark = full_text + "\n\n> ⛔ **[已取消]**"
                live.update(
                    Panel(
                        Markdown(full_text_with_mark),
                        border_style="yellow",
                        title="🤖 助手",
                        title_align="left",
                        padding=(0, 1),
                    )
                )
    finally:
        pass
    return full_text + ("\n\n[已取消]" if cancelled else "")


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
║  输入问题开始对话，输入 \help 查看帮助   ║
║  按 Ctrl+C 或输入 \exit 退出            ║
╚══════════════════════════════════════════╝"""
    console.print(welcome, style="bold blue")
    console.print()
