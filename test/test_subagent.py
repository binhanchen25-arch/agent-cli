"""SubAgent 子系统单元测试（参照 md14 设计验证）。

覆盖：
- AgentDefinition 校验
- create_subagent_context 隔离行为（abort、discovered_tools、depth）
- build_subagent_registry 三层过滤（全局禁止 / disallowed / 通配 / 白名单）
- AgentTool 派遣链路（参数校验 / 未知类型 / 深度保护 / 子 Agent 真实执行）
- 内置 Explore / Plan / General-purpose 注册正确
"""

from __future__ import annotations

import threading
import unittest
from typing import List
from unittest.mock import patch

from agents import (
    EXPLORE_AGENT,
    GENERAL_PURPOSE_AGENT,
    MAX_AGENT_DEPTH,
    PLAN_AGENT,
    AgentDefinition,
    AgentTool,
    SubagentContext,
    build_subagent_registry,
    create_subagent_context,
    get_agent_definition,
    list_agent_definitions,
)
from agents.context import AGENT_TOOL_NAME, ALL_AGENT_DISALLOWED_TOOLS
from tools.base import Tool, ToolParameter
from tools.registry import ToolRegistry


# ── 测试夹具 ──

class _StubTool(Tool):
    """最小可执行工具，便于断言 registry 内的存在/缺失。"""

    def __init__(self, name: str) -> None:
        super().__init__(name=name, description=f"stub:{name}", expandable=False)

    def get_parameters(self) -> List[ToolParameter]:
        return []

    def run(self, parameters):
        return f"stub-{self.name}"

    def is_read_only(self, parameters=None) -> bool:
        return True

    def is_concurrency_safe(self, parameters=None) -> bool:
        return True


class _StubLLM:
    """模拟 OpenAICompatLLM；AgentTool 实际调用走不到这里（被 patch 掉）。"""

    def __init__(self) -> None:
        self.config = {"api_key": "x", "base_url": "y", "model": "m"}


def _make_parent_registry(tool_names: List[str]) -> ToolRegistry:
    reg = ToolRegistry()
    for n in tool_names:
        reg.register(_StubTool(n))
    return reg


# ── AgentDefinition ──

class AgentDefinitionTests(unittest.TestCase):
    def test_empty_agent_type_raises(self):
        with self.assertRaises(ValueError):
            AgentDefinition(
                agent_type="",
                description="d",
                when_to_use="w",
                system_prompt="sp",
            )

    def test_empty_system_prompt_raises(self):
        with self.assertRaises(ValueError):
            AgentDefinition(
                agent_type="x",
                description="d",
                when_to_use="w",
                system_prompt="",
            )

    def test_negative_max_steps_raises(self):
        with self.assertRaises(ValueError):
            AgentDefinition(
                agent_type="x",
                description="d",
                when_to_use="w",
                system_prompt="sp",
                max_steps=0,
            )

    def test_wildcard_detection(self):
        a = AgentDefinition("a", "d", "w", "sp", tools=None)
        b = AgentDefinition("b", "d", "w", "sp", tools=["*"])
        c = AgentDefinition("c", "d", "w", "sp", tools=["grep"])
        self.assertTrue(a.is_wildcard_tools)
        self.assertTrue(b.is_wildcard_tools)
        self.assertFalse(c.is_wildcard_tools)


# ── SubagentContext / create_subagent_context ──

class CreateSubagentContextTests(unittest.TestCase):
    def setUp(self):
        self.parent_registry = _make_parent_registry(["grep", "view"])

    def test_depth_increments(self):
        ctx1 = create_subagent_context(
            None, self.parent_registry, EXPLORE_AGENT
        )
        self.assertEqual(ctx1.depth, 1)

        ctx2 = create_subagent_context(
            ctx1, self.parent_registry, EXPLORE_AGENT
        )
        self.assertEqual(ctx2.depth, 2)
        self.assertIs(ctx2.parent, ctx1)

    def test_discovered_tools_isolated(self):
        ctx_a = create_subagent_context(
            None, self.parent_registry, EXPLORE_AGENT
        )
        ctx_b = create_subagent_context(
            None, self.parent_registry, EXPLORE_AGENT
        )
        ctx_a.discovered_tools.add("foo")
        self.assertNotIn("foo", ctx_b.discovered_tools)

    def test_parent_abort_propagates_to_child(self):
        parent_ctx = create_subagent_context(
            None, self.parent_registry, EXPLORE_AGENT
        )
        child_ctx = create_subagent_context(
            parent_ctx, self.parent_registry, EXPLORE_AGENT
        )

        self.assertFalse(child_ctx.abort_event.is_set())
        parent_ctx.abort_event.set()
        # _link_abort 起的守护线程会在父事件触发后立即 set 子事件
        self.assertTrue(child_ctx.abort_event.wait(timeout=1.0))

    def test_child_abort_does_not_affect_parent(self):
        parent_ctx = create_subagent_context(
            None, self.parent_registry, EXPLORE_AGENT
        )
        child_ctx = create_subagent_context(
            parent_ctx, self.parent_registry, EXPLORE_AGENT
        )

        child_ctx.abort_event.set()
        # 父事件不应被反向触发
        self.assertFalse(parent_ctx.abort_event.is_set())

    def test_root_context_factory(self):
        root = SubagentContext.root(self.parent_registry)
        self.assertEqual(root.depth, 0)
        self.assertIsNone(root.parent)


# ── build_subagent_registry 三层过滤 ──

class BuildSubagentRegistryTests(unittest.TestCase):
    def setUp(self):
        # 模拟一个含 AgentTool 的父 registry
        self.parent = _make_parent_registry(
            ["grep", "view", "write_file", "edit_file", "windows_cmd",
             AGENT_TOOL_NAME]
        )

    def test_agent_tool_is_globally_blocked(self):
        """AGENT_TOOL_NAME 应被全局禁止（对应 md14 §三 ALL_AGENT_DISALLOWED_TOOLS）。"""
        self.assertIn(AGENT_TOOL_NAME, ALL_AGENT_DISALLOWED_TOOLS)
        sub = build_subagent_registry(self.parent, GENERAL_PURPOSE_AGENT)
        self.assertIsNone(sub.get_tool(AGENT_TOOL_NAME))

    def test_wildcard_inherits_all_minus_globally_blocked(self):
        sub = build_subagent_registry(self.parent, GENERAL_PURPOSE_AGENT)
        names = {m["name"] for m in sub.list_all_meta()}
        # 通配应包含所有非全局禁止的工具
        self.assertEqual(
            names,
            {"grep", "view", "write_file", "edit_file", "windows_cmd"},
        )

    def test_disallowed_tools_are_filtered(self):
        sub = build_subagent_registry(self.parent, EXPLORE_AGENT)
        names = {m["name"] for m in sub.list_all_meta()}
        # Explore 把所有写工具拉黑
        self.assertIn("grep", names)
        self.assertIn("view", names)
        self.assertNotIn("write_file", names)
        self.assertNotIn("edit_file", names)
        self.assertNotIn("windows_cmd", names)

    def test_explicit_tools_list_is_whitelist(self):
        custom = AgentDefinition(
            agent_type="only-grep",
            description="d",
            when_to_use="w",
            system_prompt="sp",
            tools=["grep"],
        )
        sub = build_subagent_registry(self.parent, custom)
        names = {m["name"] for m in sub.list_all_meta()}
        self.assertEqual(names, {"grep"})

    def test_parent_registry_not_mutated(self):
        """子 registry 构造不能影响父 registry —— 默认隔离。"""
        before = set(self.parent._tools.keys())  # noqa: SLF001
        _ = build_subagent_registry(self.parent, EXPLORE_AGENT)
        after = set(self.parent._tools.keys())  # noqa: SLF001
        self.assertEqual(before, after)


# ── 内置 Agent 注册 ──

class BuiltInRegistryTests(unittest.TestCase):
    def test_three_builtin_agents_registered(self):
        names = {d.agent_type for d in list_agent_definitions()}
        self.assertEqual(
            names, {"explore", "plan", "general-purpose"}
        )

    def test_get_unknown_returns_none(self):
        self.assertIsNone(get_agent_definition("nope"))

    def test_explore_and_plan_are_read_only(self):
        for d in (EXPLORE_AGENT, PLAN_AGENT):
            self.assertIn("write_file", d.disallowed_tools)
            self.assertIn("edit_file", d.disallowed_tools)
            self.assertIn("windows_cmd", d.disallowed_tools)


# ── AgentTool 行为 ──

class AgentToolTests(unittest.TestCase):
    def setUp(self):
        self.parent = _make_parent_registry(["grep", "view"])
        self.llm = _StubLLM()
        self.tool = AgentTool(self.parent, self.llm, parent_ctx=None)

    def test_parameters_schema_lists_required_fields(self):
        params = {p.name: p for p in self.tool.get_parameters()}
        self.assertIn("subagent_type", params)
        self.assertTrue(params["subagent_type"].required)
        self.assertIn("prompt", params)
        self.assertTrue(params["prompt"].required)
        self.assertIn("description", params)
        self.assertFalse(params["description"].required)

    def test_empty_prompt_rejected(self):
        out = self.tool.run({"subagent_type": "explore", "prompt": ""})
        self.assertIn("错误", out)

    def test_unknown_subagent_type_rejected(self):
        out = self.tool.run({"subagent_type": "bogus", "prompt": "do stuff"})
        self.assertIn("未知 subagent_type", out)

    def test_depth_guard_blocks_nested_dispatch(self):
        """当 parent_ctx.depth 已 >= MAX_AGENT_DEPTH 时，禁止再派遣。"""
        # 构造一个"已经在子 Agent 内"的 parent_ctx
        nested_ctx = SubagentContext(
            agent_definition=EXPLORE_AGENT,
            parent_registry=self.parent,
            depth=MAX_AGENT_DEPTH,
            parent=None,
        )
        nested_tool = AgentTool(self.parent, self.llm, parent_ctx=nested_ctx)
        out = nested_tool.run(
            {"subagent_type": "general-purpose", "prompt": "noop"}
        )
        self.assertIn("不允许继续派遣", out)

    def test_dispatch_invokes_run_agent(self):
        """AgentTool.run() 应该走到 run_agent；这里 patch 它返回固定流。"""
        def fake_run_agent(**kwargs):
            yield "hello "
            yield "from sub"

        with patch("agents.agent_tool.run_agent", side_effect=fake_run_agent):
            out = self.tool.run(
                {"subagent_type": "explore", "prompt": "find foo"}
            )

        self.assertIn("Subagent `explore`", out)
        self.assertIn("hello from sub", out)

    def test_is_destructive_distinguishes_read_only(self):
        # explore 禁用了写工具 → 非破坏性
        self.assertFalse(
            self.tool.is_destructive({"subagent_type": "explore"})
        )
        # general-purpose 拥有全工具 → 破坏性（兜底确认）
        self.assertTrue(
            self.tool.is_destructive({"subagent_type": "general-purpose"})
        )
        # 未知类型保守视为破坏
        self.assertTrue(
            self.tool.is_destructive({"subagent_type": "bogus"})
        )


# ── ReActAgent 兼容性 ──

class ReActAgentParentCtxTests(unittest.TestCase):
    def test_react_agent_accepts_parent_ctx_kwarg(self):
        """新增的 parent_ctx 字段不能破坏既有签名。"""
        from core.reagent import ReActAgent

        llm = _StubLLM()
        reg = _make_parent_registry(["grep"])

        a = ReActAgent("root", llm, tool_registry=reg)
        self.assertIsNone(a.parent_ctx)

        ctx = SubagentContext(
            agent_definition=EXPLORE_AGENT,
            parent_registry=reg,
            depth=1,
        )
        b = ReActAgent("child", llm, tool_registry=reg, parent_ctx=ctx)
        self.assertIs(b.parent_ctx, ctx)


if __name__ == "__main__":
    unittest.main()
