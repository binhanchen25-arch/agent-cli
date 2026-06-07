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
_NAME_SPLIT_RE = re.compile(r"[_\-\.]+|(?<=[a-z0-9])(?=[A-Z])")


def _tokenize(text: str) -> List[str]:
    """简单分词：拉丁词 + 连续中日韩字符段。"""
    return [t.lower() for t in _WORD_RE.findall(text or "")]


def _name_parts(name: str) -> List[str]:
    """把工具名拆成小段（snake_case / kebab-case / dot.case / camelCase / mcp__x__y）。"""
    parts = [p.lower() for p in _NAME_SPLIT_RE.split(name) if p]
    return parts


def _score(query_tokens: List[str], meta: Dict[str, Any]) -> int:
    """对一条工具元数据按 4 档权重打分（参考 Claude Code ToolSearch）。

    权重设计（高 → 低）：
      - name 段精确匹配（每命中一段 +10）
      - name 包含匹配 / 段包含子串（+5）
      - search_hint 匹配（+4）
      - description 匹配（+2）

    Deferred 工具额外 +1，鼓励在结果里优先被发现。
    """
    name = (meta.get("name") or "").lower()
    name_parts = _name_parts(meta.get("name") or "")
    name_parts_set = set(name_parts)
    hint = (meta.get("search_hint") or "").lower()
    desc = (meta.get("description") or "").lower()
    hint_tokens = set(_tokenize(hint))
    desc_tokens = set(_tokenize(desc))

    score = 0
    for q in query_tokens:
        if not q:
            continue
        if q in name_parts_set:
            score += 10
        elif q in name or any(q in p for p in name_parts):
            score += 5
        if q in hint_tokens or q in hint:
            score += 4
        if q in desc_tokens or q in desc:
            score += 2

    if score > 0 and not meta.get("visible", True):
        score += 1  # deferred bonus
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
                "用法：\n"
                "  · 关键词搜索：query=\"读取文件\" / query=\"slack\"\n"
                "  · 精确选择已知工具：query=\"select:foo,bar\"（按名称直接加载）\n"
                "适用场景：工具很多时定位合适的工具、`<available-deferred-tools>` 里看到名字但不知道参数。"
            ),
            expandable=False,
        )
        self._registry = registry

    def get_parameters(self) -> List[ToolParameter]:
        return [
            ToolParameter(
                name="query",
                type="string",
                description=(
                    "搜索关键词，支持中英文（如 '读取文件'、'mcp'、'web'）；"
                    "或 'select:工具名1,工具名2' 直接按名称加载多个已知工具。"
                ),
                required=True,
            ),
            ToolParameter(
                name="k",
                type="integer",
                description="最多返回多少条结果，默认 5，最大 20。仅对关键词模式有效。",
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

        # 模式 1：select:Name1,Name2 — 精确按名加载（不评分、不限 k）
        if query.lower().startswith("select:"):
            return self._run_select(query[len("select:"):])

        # 模式 2：关键词搜索
        return self._run_keyword(query, k)

    def _run_select(self, names_str: str) -> str:
        names = [n.strip() for n in names_str.split(",") if n.strip()]
        if not names:
            return "select: 后面至少需要一个工具名。例如 select:web_search,view"

        all_meta = {m["name"]: m for m in self._registry.list_all_meta()}
        results: List[Dict[str, Any]] = []
        unknown: List[str] = []
        for name in names:
            meta = all_meta.get(name)
            if meta is None:
                unknown.append(name)
                continue
            tool = self._registry.get_tool(name)  # 触发懒加载
            item: Dict[str, Any] = {
                "name": name,
                "description": meta.get("description") or "",
                "search_hint": meta.get("search_hint") or "",
                "loaded": tool is not None,
            }
            if tool is not None:
                item["parameters"] = tool.to_openai_schema()["function"]["parameters"]
            elif meta.get("error"):
                item["error"] = meta["error"]
            results.append(item)

        added = self._registry.mark_discovered([m["name"] for m in results])
        payload: Dict[str, Any] = {
            "mode": "select",
            "requested": names,
            "matched": len(results),
            "newly_discovered": added,
            "results": results,
        }
        if unknown:
            payload["unknown"] = unknown
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def _run_keyword(self, query: str, k: int) -> str:
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
                {
                    "mode": "keyword",
                    "query": query,
                    "matched": 0,
                    "note": "未找到与关键词匹配的工具。可尝试更宽泛的词，或用 select:工具名 精确加载。",
                },
                ensure_ascii=False,
                indent=2,
            )

        payload = {
            "mode": "keyword",
            "query": query,
            "matched": len(results),
            "newly_discovered": added,
            "results": results,
            "note": "newly_discovered 中的工具已加入下一轮工具集合，可直接调用。",
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)
