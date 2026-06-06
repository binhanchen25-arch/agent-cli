"""ToolSearch — 在大型工具集中按关键词检索 / 动态发现工具。

设计思路（参考 Claude Code 的 tool_search）：
- 工具数量大时（如挂载多个 MCP server 后），把所有 schema 一次性塞给 LLM 会浪费上下文。
- 解决方案：把可选工具标记为 `always_visible=False`，默认对 LLM 不可见；
  暴露一个 `tool_search` meta 工具供 LLM 主动搜索。
- 命中的工具通过 `registry.mark_discovered()` 加入"已发现"集合；
  ReActAgent 在下一轮请求前重新生成 schema 时会自动包含。
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any, Dict, List, Tuple

from tools.base import Tool, ToolParameter

if TYPE_CHECKING:
    from tools.registry import ToolRegistry


_WORD_RE = re.compile(r"[\w\u4e00-\u9fff]+")


def _tokenize(text: str) -> List[str]:
    """简单分词：拉丁词 + 连续中日韩字符段。"""
    return [t.lower() for t in _WORD_RE.findall(text or "")]


def _score(query_tokens: List[str], meta: Dict[str, Any]) -> int:
    """对一条工具元数据按关键词命中数打分。"""
    haystack_parts = [
        meta.get("name") or "",
        meta.get("description") or "",
        meta.get("search_hint") or "",
    ]
    haystack = " ".join(haystack_parts).lower()
    haystack_tokens = set(_tokenize(haystack))

    score = 0
    for q in query_tokens:
        if not q:
            continue
        # 子串匹配比 token 精确匹配更宽容（处理 "写文件" vs "write_file"）
        if q in haystack:
            score += 2
        if q in haystack_tokens:
            score += 1
    return score


class ToolSearchTool(Tool):
    """按关键词检索可用工具；命中后自动加入"已发现"集合供下一轮 LLM 调用。"""

    search_hint = "搜索可用工具、按需发现新工具"
    always_visible = True  # 自己必须始终可见

    def __init__(self, registry: "ToolRegistry") -> None:
        super().__init__(
            name="tool_search",
            description=(
                "搜索可用工具列表。返回与关键词最相关的若干工具（名称、描述、参数）。"
                "命中的工具会自动注入下一轮的工具集合，模型可直接按返回的 schema 调用。"
                "适用场景：工具很多时定位合适的工具、不确定是否存在某能力时先搜索。"
            ),
            expandable=False,
        )
        self._registry = registry

    def get_parameters(self) -> List[ToolParameter]:
        return [
            ToolParameter(
                name="query",
                type="string",
                description="搜索关键词，支持中英文（如 '读取文件'、'mcp'、'web'）。",
                required=True,
            ),
            ToolParameter(
                name="k",
                type="integer",
                description="最多返回多少条结果，默认 5，最大 20。",
                required=False,
            ),
        ]

    def is_read_only(self, parameters=None) -> bool:
        # 会修改 registry.discovered 集合，但不改任何外部状态。
        return True

    def is_concurrency_safe(self, parameters=None) -> bool:
        return True

    def run(self, parameters: Dict[str, Any]) -> str:
        query = str(parameters.get("query", "")).strip()
        if not query:
            return "query 不能为空。"
        try:
            k = max(1, min(int(parameters.get("k") or 5), 20))
        except (TypeError, ValueError):
            k = 5

        query_tokens = _tokenize(query)
        all_meta = self._registry.list_all_meta()

        scored: List[Tuple[int, Dict[str, Any]]] = []
        for meta in all_meta:
            if meta.get("name") == self.name:
                continue  # 不返回自己
            s = _score(query_tokens, meta)
            if s > 0:
                scored.append((s, meta))

        scored.sort(key=lambda x: (-x[0], x[1]["name"]))
        top = [m for _, m in scored[:k]]

        # 把命中的工具加入 discovered；同时尝试实例化以拿到 schema
        names = [m["name"] for m in top]
        added = self._registry.mark_discovered(names) if names else []

        # 拼接返回：模型最关心的是 name + description + parameters
        results: List[Dict[str, Any]] = []
        for meta in top:
            name = meta["name"]
            tool = self._registry.get_tool(name)  # 触发懒加载
            item: Dict[str, Any] = {
                "name": name,
                "description": meta.get("description") or "",
                "search_hint": meta.get("search_hint") or "",
                "loaded": tool is not None,
            }
            if tool is not None:
                # 给模型展示完整参数 schema
                schema = tool.to_openai_schema()
                item["parameters"] = schema["function"]["parameters"]
            elif meta.get("error"):
                item["error"] = meta["error"]
            results.append(item)

        if not results:
            return json.dumps(
                {"query": query, "matched": 0, "note": "未找到与关键词匹配的工具。"},
                ensure_ascii=False,
                indent=2,
            )

        payload = {
            "query": query,
            "matched": len(results),
            "newly_discovered": added,
            "results": results,
            "note": "newly_discovered 中的工具已加入下一轮工具集合，可直接调用。",
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)
