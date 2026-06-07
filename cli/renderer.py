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
    """清屏 + 光标回顶。不切备用屏幕缓冲区，
    让输出进入终端正常滚动历史 —— 用户可以
    鼠标滚轮 / Cmd+↑↓ 回看历史输出。
    """
    if os.name == "nt":
        os.system("cls")
    else:
        # 只清屏 + 光标回顶，不调 \033[?1049h（不进备用屏）。
        sys.stdout.write("\033[2J\033[H")
        sys.stdout.flush()


def exit_fullscreen():
    """退出时的清理 —— 未切备用屏，无需还原。保留函数以兼容调用点。"""
    return


def print_welcome(session_id: str | None = None):
    set_terminal_title(APP_TITLE)
    enter_fullscreen()
    session_line = ""
    if session_id:
        session_line = f"\n║  Session: {session_id[:28]:<30}║"
    welcome = """
╔══════════════════════════════════════════╗
║        🤖  MyCLI - 终端 AI 助手         ║
║                                          ║""" + session_line + """
║  输入问题开始对话，输入 \\help 查看帮助   ║
║  按 Ctrl+C 或输入 \\exit 退出            ║
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

    设计要点（解决"上滚出现无限重影"）：
      - Live 期间限定 ``vertical_overflow="crop"``：任何一帧都不超过当前可视区,
        Rich 的"上移 N 行擦除"才能命中,不会留下擦不掉的旧帧叠加。
      - Live 用 ``transient=True``：流结束/被取消时彻底擦除 Live 区域,
        避免和后续静态面板重复显示。
      - 流结束后把"完整内容"作为 *普通* ``console.print(Panel(...))`` 再打一次。
        这条输出会进入终端正常滚动缓冲区,鼠标滚轮 / Cmd+↑↓ 都能回看。

      Ctrl+C 时：关闭底层生成器（触发其 finally 清理）,把已累积的内容
      标记 ``[已取消]`` 后同样以静态面板形式打印。
    """
    full_text = ""
    console.print()
    cancelled = False
    try:
        with Live(
            console=console,
            refresh_per_second=12,
            vertical_overflow="crop",  # 防溢出留鬼影
            transient=True,             # Live 结束时擦除原地预览
        ) as live:
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
    finally:
        pass

    # Live 区已擦除 → 把"完整内容"以静态面板形式再打一次,
    # 这一帧进入终端正常滚动缓冲,可回看。
    if full_text or cancelled:
        final_md = full_text + ("\n\n> ⛔ **[已取消]**" if cancelled else "")
        console.print(
            Panel(
                Markdown(final_md),
                border_style="yellow" if cancelled else "green",
                title="🤖 助手",
                title_align="left",
                padding=(0, 1),
            )
        )
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
║  输入问题开始对话，输入 \\help 查看帮助   ║
║  按 Ctrl+C 或输入 \\exit 退出            ║
╚══════════════════════════════════════════╝"""
    console.print(welcome, style="bold blue")
    console.print()
