#!/usr/bin/env python3
"""MyCLI - Copilot 风格的终端 AI 助手。

入口已迁移至 ``entrypoints/`` 目录（参考 Claude Code 的"一份源码、多张脸"
架构）。本文件仅作为薄壳，把执行权移交给 ``entrypoints.cli.main``，
后者会根据参数走"快速路径"（如 ``--version``）或"慢路径"（拉起完整 REPL）。
"""

from entrypoints.cli import main

if __name__ == "__main__":
    main()
