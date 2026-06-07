"""自动记忆写入：每轮回答结束后异步总结并落盘。"""

from __future__ import annotations

import asyncio
import json
import re
import threading
from datetime import datetime
from typing import Optional

from memory import append_text_with_lock, consume_memory_write_marker, get_auto_memory_file

_ALLOWED_TYPES = {"user_role", "feedback_testing", "project_auth_rewrite"}
_MAX_FORMAT_RETRIES = 2


def _extract_json_block(text: str) -> dict:
    raw = str(text or "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{[\s\S]*\}", raw)
    if not match:
        return {}
    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def _build_summary_prompt(user_text: str, assistant_text: str) -> list[dict]:
    system = (
        "你是记忆分类与总结器。请根据一轮对话先分类，再输出记忆总结。\n"
        "可选分类 type 只有：user_role、feedback_testing、project_auth_rewrite。\n"
        "每轮对话只能选择一个 type，不要返回多个分类。\n"
        "输出必须是 JSON 对象，格式如下：\n"
        "{\"type\":\"...\",\"summary\":\"...\"}\n"
        "约束：\n"
        "1) summary 用 2-4 条要点，单条不超过 40 字。\n"
        "2) 仅保留长期有价值信息（偏好、约束、决策、风险）。\n"
        "3) 不要输出 JSON 以外的文本。\n"
        "4) 只输出一个 JSON 对象，不要输出数组。"
    )
    user = (
        "用户输入:\n"
        f"{user_text}\n\n"
        "助手回复:\n"
        f"{assistant_text}\n\n"
        "请直接给出记忆要点。"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def _normalize_type(value: str) -> str:
    t = str(value or "").strip().lower()
    if t in _ALLOWED_TYPES:
        return t
    return "feedback_testing"


def _is_valid_summary_payload(parsed: dict) -> bool:
    if not isinstance(parsed, dict):
        return False
    summary = str(parsed.get("summary", "") or "").strip()
    if not summary:
        return False
    if "type" in parsed:
        t = str(parsed.get("type", "") or "").strip().lower()
        if t and t not in _ALLOWED_TYPES:
            return False
    return True


async def _invoke_summary_json(llm, prompt_messages: list[dict]) -> dict:
    """调用 LLM 并确保返回可解析的 JSON 结构；格式不对时有限重试。"""
    base_messages = list(prompt_messages)
    for attempt in range(_MAX_FORMAT_RETRIES + 1):
        messages = list(base_messages)
        if attempt > 0 and messages and messages[0].get("role") == "system":
            # 重试时仅强化 system 约束，避免把纠错提示混入会话语义。
            messages[0] = {
                **messages[0],
                "content": str(messages[0].get("content", ""))
                + "\n\n上一次输出格式不合法。"
                + "严格要求：只输出 JSON 对象，不要输出任何额外文字。",
            }
        raw = await asyncio.to_thread(llm.invoke, messages)
        parsed = _extract_json_block(raw)
        if _is_valid_summary_payload(parsed):
            return parsed
    return {}


async def write_auto_memory_async(
    *,
    llm,
    user_text: str,
    assistant_text: str,
    memory_type: str = "auto",
) -> None:
    """异步总结并写入自动记忆。

    若本轮已由 memory 工具执行写入，则自动写入会被跳过。
    """
    if consume_memory_write_marker():
        return

    if not getattr(llm, "config", {}).get("api_key"):
        return

    prompt_messages = _build_summary_prompt(user_text=user_text, assistant_text=assistant_text)
    parsed = await _invoke_summary_json(llm, prompt_messages)
    if not parsed:
        return

    if memory_type in _ALLOWED_TYPES:
        final_type = memory_type
        summary = str(parsed.get("summary", "") or "").strip()
    else:
        final_type = _normalize_type(parsed.get("type", ""))
        summary = str(parsed.get("summary", "") or "").strip()

    if not summary or summary.startswith("❌ API 错误"):
        return

    now = datetime.now().isoformat(timespec="seconds")
    block = (
        f"\n## {now}\n"
        f"分类: {final_type}\n"
        f"用户: {user_text[:200]}\n"
        f"记忆:\n{summary}\n"
    )
    target = get_auto_memory_file(final_type)
    await asyncio.to_thread(append_text_with_lock, target, block)


def schedule_auto_memory_write(
    *,
    llm,
    user_text: str,
    assistant_text: str,
    memory_type: str = "auto",
) -> Optional[threading.Thread]:
    """以后台线程触发自动记忆写入，避免阻塞 CLI。"""

    def _runner() -> None:
        try:
            asyncio.run(
                write_auto_memory_async(
                    llm=llm,
                    user_text=user_text,
                    assistant_text=assistant_text,
                    memory_type=memory_type,
                )
            )
        except Exception:
            # 自动记忆失败不能影响主流程
            return

    t = threading.Thread(target=_runner, name="auto-memory-writer", daemon=True)
    t.start()
    return t
