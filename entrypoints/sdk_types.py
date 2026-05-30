"""入口形态二的公共表面 —— 对应 Claude Code 的 ``agentSdkTypes.ts``。

外部 Python 程序通过本模块使用 MyCLI 的 agent 能力，例如::

    from entrypoints.sdk_types import query, QueryOptions, ToolParameter

    answer = query("当前时间是几点", options=QueryOptions(max_steps=5))

设计要点：

- 只暴露稳定的"公共表面"：类型 / schema / 几个便捷函数。
- 类型与 schema 从 ``entrypoints.sdk`` 子目录 re-export，外部用户不必了解内部布局。
- 与 Claude Code 不同，Python 这边的运行时函数 **直接** 调用内部实现，
  不像 TS 端那样 ``throw new Error('not implemented')`` 等 bundle 注入 ——
  Python 没有那一步打包注入流程，留 stub 反而会让用户困惑。
"""

from __future__ import annotations

import json
from typing import Iterable, Optional

from entrypoints.sdk.control_schemas import QueryOptions
from entrypoints.sdk.core_schemas import ToolParameter
from entrypoints.sdk.core_types import LLMResponse, ToolCall
from tools.base import Tool, UserRefusedError
from tools.registry import ToolRegistry

__all__ = [
    "LLMResponse",
    "QueryOptions",
    "Tool",
    "ToolCall",
    "ToolParameter",
    "ToolRegistry",
    "UserRefusedError",
    "create_sdk_tool_registry",
    "dump_schema",
    "query",
]


def query(question: str, *, options: Optional[QueryOptions] = None) -> str:
    """一次性 agent 查询：构造 ReActAgent 并返回最终文本回复。

    Args:
        question: 用户问题。
        options:  可选 ``QueryOptions``。

    Returns:
        Agent 的最终回答字符串。
    """
    from core.config import load_config
    from core.llm import OpenAICompatLLM
    from core.reagent import ReActAgent
    from tools.builtin import set_allow_all_windows_cmd

    opts = options or QueryOptions()

    if opts.allow_all_commands:
        set_allow_all_windows_cmd(True)

    config = load_config()
    llm = OpenAICompatLLM(config)
    agent = ReActAgent(
        name="SDK",
        llm=llm,
        max_steps=opts.max_steps,
        custom_prompt=opts.system_prompt,
    )
    return agent.run(question)


def create_sdk_tool_registry(extra_tools: Optional[Iterable[Tool]] = None) -> ToolRegistry:
    """返回包含内置工具（可选叠加用户自定义工具）的 ``ToolRegistry``。

    便于 SDK 用户基于默认能力快速组装一个适合自己场景的工具集。
    """
    from tools.builtin import default_tool_registry

    reg = default_tool_registry()
    if extra_tools:
        reg.register_many(list(extra_tools))
    return reg


def dump_schema() -> str:
    """打印 SDK 公共表面的关键 schema（OpenAI tools schema + QueryOptions）。

    供 ``mycli sdk-schema`` 子命令使用，方便外部用户在不写代码的情况下
    了解 SDK 暴露的工具和选项结构。
    """
    from tools.builtin import default_tool_registry

    payload = {
        "version": 1,
        "query_options": QueryOptions.model_json_schema(),
        "tools": default_tool_registry().get_openai_tools_schema(),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)
