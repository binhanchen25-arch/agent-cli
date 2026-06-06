"""联网搜索工具：基于 DuckDuckGo（无需 API Key）。"""

from __future__ import annotations

from typing import Any, Dict, List

from tools.base import Tool, ToolParameter


class WebSearchTool(Tool):
    """使用 DuckDuckGo 搜索网络内容，返回标题、摘要和链接。"""

    search_hint = "联网搜索网络信息"

    def __init__(self) -> None:
        super().__init__(
            name="web_search",
            description=(
                "联网搜索：使用 DuckDuckGo 查询网络内容，返回标题、摘要和链接。"
                "适合查询实时信息、新闻、技术文档等。"
                "参数 query 为搜索关键词，max_results 为返回条数（默认 5，最多 10）。"
            ),
            expandable=False,
        )

    def get_parameters(self) -> List[ToolParameter]:
        return [
            ToolParameter(
                name="query",
                type="string",
                description="搜索关键词，支持中英文。",
                required=True,
            ),
            ToolParameter(
                name="max_results",
                type="integer",
                description="返回结果条数，默认 5，最多 10。",
                required=False,
            ),
        ]

    def is_read_only(self, parameters=None) -> bool:
        return True

    def is_concurrency_safe(self, parameters=None) -> bool:
        return True

    def run(self, parameters: Dict[str, Any]) -> str:
        try:
            from ddgs import DDGS  # type: ignore
        except ImportError:
            return (
                "缺少依赖 `ddgs`，请先执行：\n"
                "  pip install ddgs"
            )

        query = str(parameters.get("query", "")).strip()
        if not query:
            return "搜索关键词不能为空。"

        try:
            max_results = min(int(parameters.get("max_results") or 5), 10)
        except (ValueError, TypeError):
            max_results = 5

        try:
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=max_results))
        except Exception as e:
            return f"搜索失败: {e}"

        if not results:
            return f"未找到与 `{query}` 相关的结果。"

        lines: List[str] = [f"搜索：{query}（共 {len(results)} 条）\n"]
        for i, r in enumerate(results, 1):
            title = r.get("title", "(无标题)")
            body = r.get("body", "").strip()
            href = r.get("href", "")
            lines.append(f"{i}. **{title}**")
            if body:
                lines.append(f"   {body[:200]}{'...' if len(body) > 200 else ''}")
            if href:
                lines.append(f"   {href}")
            lines.append("")

        return "\n".join(lines).rstrip()
