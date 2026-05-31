"""入口形态一：交互式 / 非交互式 CLI。

参考 Claude Code 的 ``cli.tsx`` —— 本文件扮演"门房"角色：
在加载重型模块（OpenAI SDK / Rich / prompt_toolkit）之前，
先看清来人是谁；能就地打发的就当场打发，省下后续几百毫秒的启动开销。

快速路径示例：

- ``mycli --version`` 只 ``print`` 一个内联常量就 ``return``
- ``mycli --help``    只打印静态帮助文本
- ``mycli --config-path`` 只解析配置文件路径
- ``mycli sdk-schema`` 动态 ``import`` SDK 公共表面并 dump JSON Schema

只有所有快速路径都不命中，才会走到文件末尾的 ``_run_full_app()``，
通过 ``entrypoints.init.init_app()`` 把全量 ``ChatApp`` 拉起来。
"""

from __future__ import annotations

import sys
from typing import List

VERSION = "0.1.0"

_HELP_TEXT = """🤖 MyCLI - 终端 AI 助手

用法:
    mycli                 启动交互式 REPL
    mycli --version       显示版本号
    mycli --help          显示本帮助
    mycli --config-path   打印配置文件路径
    mycli sdk-schema      打印 Agent SDK 公共表面的 JSON Schema

更多 REPL 内命令（如 \\react、\\allow、\\model）请在交互模式下输入 \\help 查看。
"""


def _print_version() -> None:
    print(f"{VERSION} (MyCLI)")


def _print_help() -> None:
    print(_HELP_TEXT)


def _print_config_path() -> None:
    """只 import config 模块，不加载 LLM/Rich/prompt_toolkit。"""
    from core.config import CONFIG_FILE

    print(CONFIG_FILE)


def _run_sdk_schema() -> None:
    from entrypoints.sdk_types import dump_schema

    print(dump_schema())


def _run_full_app() -> None:
    """慢路径：拉起完整 ChatApp。"""
    from entrypoints.init import init_app

    app = init_app()
    app.run()


def main(argv: List[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)

    # === 快速路径：不加载重型模块 ===
    if len(args) == 1 and args[0] in ("--version", "-v", "-V"):
        _print_version()
        return

    if len(args) == 1 and args[0] in ("--help", "-h"):
        _print_help()
        return

    if len(args) == 1 and args[0] == "--config-path":
        _print_config_path()
        return

    if args and args[0] == "sdk-schema":
        _run_sdk_schema()
        return

    # === 慢路径：完整 REPL ===
    _run_full_app()


if __name__ == "__main__":
    main()
