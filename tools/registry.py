"""工具注册表：支持 ReAct 文本格式和 Function Calling 两种调用方式。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple

from runtime_log import log_event
from tools.base import Tool, UserRefusedError
from tools.confirm import (
    confirm_in_cli,
    is_confirm_explicitly_set,
    should_confirm_tool_call,
    strip_confirm_parameter,
)


@dataclass
class _LazyEntry:
    """懒加载工具的占位条目：实例化由 factory 完成。"""

    name: str
    factory: Callable[[], Tool]
    description: str = ""
    search_hint: str = ""
    always_visible: bool = True
    # 创建失败原因（如 ImportError）。失败后不再重试，仅在 tool_search 中给出提示。
    error: Optional[str] = field(default=None)


class ToolRegistry:
    """登记 `Tool` 实例；支持文本和结构化参数两种执行方式。

    新增能力：
    - **懒加载**：`register_lazy(name, factory, ...)` 在首次需要时才实例化工具，
      用于规避可选依赖（如 ddgs / python-docx / mcp）缺失导致启动失败。
    - **动态可见集**：`always_visible=False` 的工具默认不进入 LLM 的 schema；
      通过 `mark_discovered(names)` 把工具加入"已发现"集合后才暴露。
      用于配合 `tool_search` 在工具数量很大时按需展开。
    """

    def __init__(self, config: Optional[dict] = None) -> None:
        self._tools: Dict[str, Tool] = {}
        self._lazy: Dict[str, _LazyEntry] = {}
        self._discovered: Set[str] = set()
        self.config = config or {}
        # 关闭钩子：MCP server 等需要在 CLI 退出时清理。
        self._closers: List[Callable[[], None]] = []

    # ── 注册 ──

    def register(self, tool: Tool) -> None:
        if tool.expandable:
            expanded = tool.get_expanded_tools()
            if expanded:
                for t in expanded:
                    self._tools[t.name] = t
                return
        self._tools[tool.name] = tool

    def register_many(self, tools: List[Tool]) -> None:
        for t in tools:
            self.register(t)

    def register_lazy(
        self,
        name: str,
        factory: Callable[[], Tool],
        description: str = "",
        search_hint: str = "",
        always_visible: bool = True,
    ) -> None:
        """登记一个工具的工厂，首次访问时实例化。

        Args:
            name: 工具唯一名（必须与 factory 返回的 tool.name 一致）。
            factory: 无参可调用，返回 `Tool` 实例。
            description: 工具简介（用于 tool_search 检索，未实例化时使用）。
            search_hint: 关键词提示（与 description 共同参与匹配）。
            always_visible: False 表示默认对 LLM 不可见，仅 tool_search 可发现。
        """
        self._lazy[name] = _LazyEntry(
            name=name,
            factory=factory,
            description=description,
            search_hint=search_hint,
            always_visible=always_visible,
        )

    def add_closer(self, closer: Callable[[], None]) -> None:
        """登记一个清理回调（如 MCP 子进程关闭）。"""
        self._closers.append(closer)

    def close(self) -> None:
        """逆序触发所有清理回调；异常静默吞掉。"""
        while self._closers:
            cb = self._closers.pop()
            try:
                cb()
            except Exception:
                pass

    # ── 懒加载 / 可见集 ──

    def _realize(self, name: str) -> Optional[Tool]:
        """把 _lazy[name] 实例化到 _tools。失败则记录错误并返回 None。"""
        if name in self._tools:
            return self._tools[name]
        entry = self._lazy.get(name)
        if entry is None:
            return None
        if entry.error:
            return None
        try:
            tool = entry.factory()
        except Exception as e:  # 依赖缺失、网络失败等
            entry.error = f"{type(e).__name__}: {e}"
            return None
        # 把元数据回填到 tool（若 tool 没自带）
        if not getattr(tool, "search_hint", "") and entry.search_hint:
            tool.search_hint = entry.search_hint
        self._tools[tool.name] = tool
        # 不立刻删除 lazy 条目 —— 留着供 list_all_meta() 查询元信息
        return tool

    def mark_discovered(self, names: Iterable[str]) -> List[str]:
        """把工具名加入"已发现"集合；下一轮 schema 将包含这些工具。

        返回实际新增到集合中的名字列表。未知名字会被静默忽略。
        """
        added: List[str] = []
        for name in names:
            if name in self._tools or name in self._lazy:
                if name not in self._discovered:
                    self._discovered.add(name)
                    added.append(name)
        return added

    def get_tool(self, name: str) -> Optional[Tool]:
        if name in self._tools:
            return self._tools[name]
        return self._realize(name)

    def _iter_visible_tools(self) -> Iterable[Tool]:
        """生成所有当前对 LLM 可见的工具实例（按需触发懒加载）。"""
        seen: Set[str] = set()
        # 已实例化的：always_visible 或在 discovered 集合中
        for name, tool in list(self._tools.items()):
            if getattr(tool, "always_visible", True) or name in self._discovered:
                seen.add(name)
                yield tool
        # 未实例化的：always_visible 或 discovered 触发实例化
        for name, entry in list(self._lazy.items()):
            if name in seen:
                continue
            if entry.always_visible or name in self._discovered:
                tool = self._realize(name)
                if tool is not None:
                    yield tool

    def list_all_meta(self) -> List[Dict[str, Any]]:
        """列出所有已知工具（含懒加载未实例化的）的元信息，供 tool_search 检索。"""
        out: List[Dict[str, Any]] = []
        seen: Set[str] = set()
        for name, tool in self._tools.items():
            seen.add(name)
            out.append({
                "name": name,
                "description": tool.description,
                "search_hint": getattr(tool, "search_hint", ""),
                "loaded": True,
                "visible": getattr(tool, "always_visible", True) or name in self._discovered,
                "error": None,
            })
        for name, entry in self._lazy.items():
            if name in seen:
                continue
            out.append({
                "name": name,
                "description": entry.description,
                "search_hint": entry.search_hint,
                "loaded": False,
                "visible": entry.always_visible or name in self._discovered,
                "error": entry.error,
            })
        return out

    def list_deferred_tools(self) -> List[Dict[str, str]]:
        """返回当前 "存在但对 LLM 不可见" 的工具名单。

        用于在每轮请求前向 system prompt 注入 ``<available-deferred-tools>``
        提醒块，让模型知道存在哪些可被 `tool_search` 发现的工具。
        只返回轻量字段（name + search_hint/description 摘要），不返回 schema。
        """
        out: List[Dict[str, str]] = []
        for meta in self.list_all_meta():
            if meta.get("visible"):
                continue
            if meta.get("error"):
                continue  # 加载失败的不必告诉模型
            hint = (meta.get("search_hint") or meta.get("description") or "").strip()
            # 一句话限长，避免序列到 prompt 里占太多 token
            if len(hint) > 80:
                hint = hint[:77] + "…"
            out.append({"name": meta["name"], "hint": hint})
        out.sort(key=lambda x: x["name"])
        return out

    # ── 公共 schema / 描述 ──

    def get_openai_tools_schema(self) -> List[Dict[str, Any]]:
        """返回所有已启用且对当前轮可见的工具 schema。

        按 ``tool.name`` 排序，以最大化服务端 prompt cache 命中率
        （tools 列表顺序变化会使 cache key 失效）。

        注意：本方法应在 ReActAgent 每一步发请求前重新调用 —— `tool_search`
        触发 `mark_discovered()` 后，下一轮 schema 才会包含新发现的工具。
        """
        schemas = [
            t.to_openai_schema()
            for t in self._iter_visible_tools()
            if t.is_enabled()
        ]
        schemas.sort(key=lambda s: s["function"]["name"])
        return schemas

    def get_tools_description(self) -> str:
        tools = list(self._iter_visible_tools())
        if not tools:
            return "（当前未注册任何工具）"
        lines: List[str] = []
        for t in tools:
            if not t.is_enabled():
                continue
            params = t.get_parameters()
            if not params:
                lines.append(f"- **{t.name}**: {t.description}")
                continue
            plist = []
            for p in params:
                req = "必填" if p.required else "可选"
                plist.append(f"`{p.name}` ({p.type}, {req}): {p.description}")
            lines.append(f"- **{t.name}**: {t.description}\n  参数: " + "；".join(plist))
        return "\n".join(lines)

    # ── 执行入口 ──

    def _raw_to_params(self, tool: Tool, raw_input: str) -> Dict[str, Any]:
        params_def = tool.get_parameters()
        if not params_def:
            return {}
        if len(params_def) == 1:
            p0 = params_def[0]
            return {p0.name: raw_input}
        stripped = raw_input.strip()
        if stripped.startswith("{"):
            try:
                data = json.loads(stripped)
            except json.JSONDecodeError:
                return {}
            if isinstance(data, dict):
                return data
            return {}
        return {}

    def execute_tool(self, name: str, raw_input: str) -> str:
        """ReAct 模式：从原始字符串解析参数并执行。"""
        tool = self.get_tool(name)
        if not tool:
            return f"未知工具: {name}。请从可用工具中选择。"

        parameters = self._raw_to_params(tool, raw_input)
        return self._run_with_validation(tool, parameters)

    def execute_tool_by_params(self, name: str, parameters: Dict[str, Any]) -> str:
        """Function Calling 模式：直接接收结构化参数并执行。"""
        tool = self.get_tool(name)
        if not tool:
            return f"未知工具: {name}。可用工具: {list(self._tools.keys()) + list(self._lazy.keys())}"

        return self._run_with_validation(tool, parameters)

    def _resolve_confirm(self, tool: Tool, parameters: Dict[str, Any]) -> bool:
        """统一决策是否需要弹窗确认。

        优先级（高 → 低）：
            1. 模型显式传 confirm=true/false → 完全听模型。
            2. 模型未传 + 工具自报 destructive → 兜底要求确认（防误删）。
            3. 否则走全局默认（默认 False，由模型自主判断）。
        """
        if is_confirm_explicitly_set(parameters):
            return should_confirm_tool_call(parameters)

        cleaned = strip_confirm_parameter(parameters)
        try:
            destructive = bool(tool.is_destructive(cleaned))
        except Exception:
            destructive = False
        if destructive:
            return True

        return should_confirm_tool_call(parameters)

    def partition_tool_calls(
        self, tool_calls: List[Any]
    ) -> List[Tuple[bool, List[Any]]]:
        """把一组 tool_calls 切成 (is_concurrent_batch, [calls]) 序列。

        相邻的 concurrency_safe 工具合并成一个并发 batch；其他工具各自独立串行。
        需要弹窗确认的工具一律退化为串行（弹窗是 modal，不能并行）。
        """
        batches: List[Tuple[bool, List[Any]]] = []
        for tc in tool_calls:
            tool = self.get_tool(getattr(tc, "name", ""))
            args = getattr(tc, "arguments", {}) or {}

            safe = False
            if tool is not None:
                try:
                    safe = bool(tool.is_concurrency_safe(args))
                except Exception:
                    safe = False
                if safe and self._resolve_confirm(tool, args):
                    safe = False

            if batches and safe and batches[-1][0]:
                batches[-1][1].append(tc)
            else:
                batches.append((safe, [tc]))
        return batches

    def _run_with_validation(self, tool: Tool, parameters: Dict[str, Any]) -> str:
        """统一的参数验证 + 执行路径。"""
        cleaned_parameters = strip_confirm_parameter(parameters)
        log_event(
            self.config,
            "tool_started",
            tool=tool.name,
            parameters=cleaned_parameters,
        )

        if self._resolve_confirm(tool, parameters):
            detail = (
                f"工具: {tool.name}\n"
                f"参数: {json.dumps(cleaned_parameters, ensure_ascii=False, indent=2)}"
            )
            approved = confirm_in_cli(detail)
            if not approved:
                log_event(
                    self.config,
                    "tool_refused",
                    tool=tool.name,
                    parameters=cleaned_parameters,
                )
                raise UserRefusedError(tool.name, "用户在确认弹窗中拒绝执行")

        if not tool.validate_parameters(cleaned_parameters):
            needed = [p.name for p in tool.get_parameters() if p.required]
            log_event(
                self.config,
                "tool_invalid_parameters",
                tool=tool.name,
                provided=list(cleaned_parameters.keys()),
                required=needed,
            )
            return (
                f"参数不完整。工具 `{tool.name}` 需要字段: {needed}。"
                f"收到: {list(cleaned_parameters.keys())}"
            )
        try:
            result = tool.run(cleaned_parameters)
            log_event(
                self.config,
                "tool_finished",
                tool=tool.name,
                result_preview=str(result)[:200],
            )
            return result
        except UserRefusedError:
            log_event(
                self.config,
                "tool_refused",
                tool=tool.name,
                parameters=cleaned_parameters,
            )
            raise
        except Exception as e:
            log_event(
                self.config,
                "tool_failed",
                tool=tool.name,
                error=str(e),
            )
            return f"工具执行错误: {e}"
