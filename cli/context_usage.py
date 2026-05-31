"""上下文统计工具：计算 messages 的 token 与上下文占用。"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from constants.model_context import ModelContextConstants

_MODEL_CONTEXT_WINDOWS = ModelContextConstants.MODEL_CONTEXT_WINDOWS


def _resolve_context_window(model: str, override: Optional[int] = None) -> int:
    """解析上下文窗口大小，优先使用显式传入值。"""
    if override and override > 0:
        return override

    if model in _MODEL_CONTEXT_WINDOWS:
        return _MODEL_CONTEXT_WINDOWS[model]

    # 尽量按前缀做兜底
    if model.startswith("gpt-4o"):
        return 128000
    if model.startswith("gpt-4.1"):
        return 1047576
    if model.startswith("gpt-4"):
        return 128000
    if model.startswith("gpt-3.5"):
        return 16385
    if model.startswith(("o1", "o3", "o4")):
        return 200000
    if model.startswith("claude"):
        return 200000
    if model.startswith("deepseek"):
        return 64000
    if model.startswith("gemini"):
        return 1048576
    if model.startswith("qwen"):
        return 131072
    if model.startswith("llama"):
        return 131072
    if model.startswith("grok"):
        return 131072

    # 未知模型默认给较新的通用窗口
    return 128000


def _stringify_content(value: Any) -> str:
    """把 message 字段安全转成字符串，便于统一计数。"""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        return str(value)


def _estimate_tokens_fallback(text: str) -> int:
    """无 tiktoken 时的估算：兼顾英文与中文场景。"""
    if not text:
        return 0

    # 英文经验：约 4 字符 ≈ 1 token
    by_chars = max(1, round(len(text) / 4))
    # CJK 经验：UTF-8 三字节字符常接近 1 token
    by_bytes = max(1, round(len(text.encode("utf-8")) / 3))
    return max(by_chars, by_bytes)


def count_message_tokens(messages: List[dict], model: str) -> int:
    """
    统计 messages 的 token 数。

    优先使用 tiktoken 做精确计数；若环境未安装 tiktoken，自动回退到估算。
    """
    try:
        import tiktoken  # type: ignore

        try:
            encoding = tiktoken.encoding_for_model(model)
        except KeyError:
            encoding = tiktoken.get_encoding("cl100k_base")

        # 兼容 Chat Completions 的近似计数规则
        tokens_per_message = 3
        tokens_per_name = 1
        total = 0

        for message in messages:
            total += tokens_per_message
            for key, value in message.items():
                text = _stringify_content(value)
                total += len(encoding.encode(text))
                if key == "name":
                    total += tokens_per_name

        # assistant 回复前缀开销
        total += 3
        return total

    except Exception:
        # 回退估算
        total = 0
        for message in messages:
            total += 4
            for value in message.values():
                total += _estimate_tokens_fallback(_stringify_content(value))
        total += 2
        return total


def calculate_context_usage(
    messages: List[dict],
    model: str,
    context_window: Optional[int] = None,
) -> Dict[str, float]:
    """
    计算当前对话占用情况。

    返回字段：
    - token_count: 当前 messages 估算/统计 token 数
    - context_window: 上下文窗口大小
    - context_ratio: 占用比例（0-1）
    - context_percent: 占用百分比（0-100）
    - remaining_tokens: 剩余上下文 token
    """
    token_count = count_message_tokens(messages, model)
    window = _resolve_context_window(model, context_window)
    ratio = min(1.0, token_count / window) if window > 0 else 0.0
    percent = round(ratio * 100, 2)
    remaining = max(0, window - token_count)

    return {
        "token_count": float(token_count),
        "context_window": float(window),
        "context_ratio": ratio,
        "context_percent": percent,
        "remaining_tokens": float(remaining),
    }
