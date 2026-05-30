"""MyCLI 用户钩子文件 — 由 core/hooks.py 动态加载。

约定：在此文件中按名字定义函数，MyCLI 在合适的时机会自动调用。
保存后无需重启 —— 基于文件 mtime 的热重载会自动生效。

当前支持的 hook：

    before_step(step: int, messages: list[dict]) -> list[dict] | None
        ReActAgent 每次调用 LLM 之前触发。
        返回 None  → 不改 messages
        返回 list  → 用返回值替换 messages
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

# 日志文件位置：<cwd>/.mycli/agent.log
LOG_FILE = Path(__file__).resolve().parent / "agent.log"

# 上下文窗口：超过这个数就只保留 system + 最近的 N-1 条
MAX_CONTEXT_MESSAGES = 20

# 每步注入的额外提示（设为 None 关闭）
EXTRA_REMINDER: Optional[str] = None
# 示例：EXTRA_REMINDER = "请优先使用 grep 工具定位关键词，再用 view 读取片段。"


def before_step(step: int, messages: List[dict]) -> Optional[List[dict]]:
    """每次 LLM 调用前触发。"""

    # ── 1. 日志记录：把每步的上下文 dump 到 .mycli/agent.log ──
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"\n=== step {step} ({len(messages)} messages) ===\n")
            f.write(json.dumps(messages, ensure_ascii=False, indent=2))
            f.write("\n")
    except OSError:
        # 写日志失败不应阻塞 agent，静默忽略
        pass

    # ── 2. 上下文裁剪：太长就只留 system + 最近 N-1 条 ──
    if len(messages) > MAX_CONTEXT_MESSAGES:
        system_msgs = [m for m in messages if m.get("role") == "system"]
        recent = messages[-(MAX_CONTEXT_MESSAGES - len(system_msgs)):]
        messages = system_msgs + recent

    # ── 3. 注入额外提示（可选）──
    if EXTRA_REMINDER:
        messages = messages + [{"role": "system", "content": EXTRA_REMINDER}]

    return messages
