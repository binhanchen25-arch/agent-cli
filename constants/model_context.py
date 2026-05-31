"""模型上下文窗口常量定义。"""

from __future__ import annotations

from typing import Dict


class ModelContextConstants:
    """模型上下文窗口常量（静态）。"""

    # 常见模型上下文窗口（可按需扩展）
    MODEL_CONTEXT_WINDOWS: Dict[str, int] = {
        # OpenAI
        "gpt-4o": 128000,
        "gpt-4o-mini": 128000,
        "gpt-4-turbo": 128000,
        "gpt-4": 8192,
        "gpt-3.5-turbo": 16385,
        "gpt-4.1": 1047576,
        "gpt-4.1-mini": 1047576,
        "o1": 200000,
        "o3": 200000,
        "o4-mini": 200000,

        # Anthropic Claude
        "claude-3-haiku": 200000,
        "claude-3-sonnet": 200000,
        "claude-3-opus": 200000,
        "claude-3-5-haiku": 200000,
        "claude-3-5-sonnet": 200000,
        "claude-3-7-sonnet": 200000,
        "claude-sonnet-4": 200000,
        "claude-opus-4": 200000,

        # DeepSeek
        "deepseek-chat": 64000,
        "deepseek-coder": 64000,
        "deepseek-reasoner": 64000,
        "deepseek-v3": 64000,
        "deepseek-r1": 64000,

        # Google Gemini
        "gemini-1.5-flash": 1048576,
        "gemini-1.5-pro": 2097152,
        "gemini-2.0-flash": 1048576,
        "gemini-2.5-pro": 1048576,

        # Qwen
        "qwen-turbo": 131072,
        "qwen-plus": 131072,
        "qwen-max": 32768,
        "qwen2.5-72b-instruct": 131072,
        "qwen2.5-coder-32b-instruct": 131072,

        # Meta Llama (常见推理服务配置)
        "llama-3.1-8b-instruct": 131072,
        "llama-3.1-70b-instruct": 131072,
        "llama-3.1-405b-instruct": 131072,
        "llama-3.2-3b-instruct": 131072,

        # xAI Grok
        "grok-2": 131072,
        "grok-2-mini": 131072,
    }
