"""共享初始化模块 —— 类似 Claude Code 的 ``init.ts``。

仅由 CLI 慢路径（``entrypoints/cli.py`` 的 ``_run_full_app``）调用；
快速路径（``--version`` / ``--help`` 等）不会触发，从而保持启动开销最小。
"""

from __future__ import annotations


def init_app():
    """构造并返回完整的 ``ChatApp`` 实例（含配置加载、LLM、Prompt session）。

    在这里做一次性的 ``import``，把重型依赖延迟到真正需要 REPL 时才加载。
    """
    from memory import ensure_cli_memory_structure
    from cli.app import ChatApp

    ensure_cli_memory_structure()
    return ChatApp()
