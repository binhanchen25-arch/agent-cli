"""网页抓取工具：获取指定 URL 的页面正文。"""

from __future__ import annotations

import re
import urllib.request
import urllib.error
from typing import Any, Dict, List

from tools.base import Tool, ToolParameter

_MAX_CHARS = 8000  # 返回给模型的最大字符数


def _strip_html(html: str) -> str:
    """简单去除 HTML 标签，保留可读文本。"""
    # 移除 script / style 块
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    # 把块级标签换成换行
    html = re.sub(r"<(br|p|div|h[1-6]|li|tr)[^>]*>", "\n", html, flags=re.I)
    # 去掉其余标签
    html = re.sub(r"<[^>]+>", "", html)
    # 合并空白
    html = re.sub(r"\n{3,}", "\n\n", html)
    html = re.sub(r"[ \t]+", " ", html)
    return html.strip()


class FetchUrlTool(Tool):
    """抓取指定 URL 的页面正文内容。"""

    def __init__(self) -> None:
        super().__init__(
            name="fetch_url",
            description=(
                "抓取指定 URL 的网页内容并返回纯文本正文。"
                "适合在 web_search 获取链接后，进一步读取页面详情。"
                f"返回内容最多 {_MAX_CHARS} 字符。"
            ),
            expandable=False,
        )

    def get_parameters(self) -> List[ToolParameter]:
        return [
            ToolParameter(
                name="url",
                type="string",
                description="要抓取的网页 URL，必须以 http:// 或 https:// 开头。",
                required=True,
            ),
        ]

    def run(self, parameters: Dict[str, Any]) -> str:
        url = str(parameters.get("url", "")).strip()

        if not url:
            return "url 不能为空。"
        if not url.startswith(("http://", "https://")):
            return "url 必须以 http:// 或 https:// 开头。"

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (compatible; MyCLI-Agent/1.0)"
            )
        }

        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as resp:
                content_type = resp.headers.get("Content-Type", "")
                raw = resp.read()
        except urllib.error.HTTPError as e:
            return f"HTTP 错误 {e.code}: {e.reason}  ({url})"
        except urllib.error.URLError as e:
            return f"无法访问 URL: {e.reason}  ({url})"
        except Exception as e:
            return f"抓取失败: {e}"

        # 根据 Content-Type 解码
        charset = "utf-8"
        m = re.search(r"charset=([^\s;]+)", content_type, re.I)
        if m:
            charset = m.group(1).strip().strip('"')

        try:
            text = raw.decode(charset, errors="replace")
        except (LookupError, UnicodeDecodeError):
            text = raw.decode("utf-8", errors="replace")

        if "html" in content_type.lower():
            text = _strip_html(text)

        if len(text) > _MAX_CHARS:
            text = text[:_MAX_CHARS] + f"\n\n... [内容已截断，共 {len(text)} 字符]"

        return f"URL: {url}\n\n{text}"
