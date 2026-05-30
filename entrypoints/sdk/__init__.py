"""Agent SDK 的内部实现层。

参考 Claude Code 的 ``entrypoints/sdk/`` 子目录：本目录只放被
``entrypoints/sdk_types.py`` re-export 的内部 schema / 数据类型，
不直接暴露给外部用户。外部用户应当只 ``import`` ``entrypoints.sdk_types``。
"""
