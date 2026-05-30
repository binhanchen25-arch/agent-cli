"""MyCLI 入口层 —— 参考 Claude Code 的"一份源码，多张脸"架构。

本目录把面向不同外部使用者的入口集中在一处：

- ``cli``       交互式 / 非交互式 CLI（用户在终端执行 ``mycli``）
- ``sdk``       Agent SDK 的内部实现（数据类型 + 控制 schema）
- ``sdk_types`` SDK 的公共表面（其他 Python 程序 ``import`` 的入口）
- ``init``      共享初始化模块（仅 CLI 主流程调用，非快速路径）

设计原则与 Claude Code 一致：模块顶层不做重型 import，所有重型依赖
（OpenAI SDK、Rich、prompt_toolkit）都延迟到真正需要时再 ``import``，
让 ``--version`` / ``--help`` 这类快速路径几乎零开销。
"""
