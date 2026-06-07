"""Session 级 memory：懒创建 summary.md，并按阈值增量更新。"""

from __future__ import annotations

import asyncio
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from memory import append_text_with_lock, get_project_memory_dir

# 首次抽取阈值：对话累计 token 达到该值才会首次创建 summary.md
SESSION_FIRST_EXTRACT_TOKEN_THRESHOLD = 10000
# 后续增量更新的“三阈值”
SESSION_DELTA_TOKEN_THRESHOLD = 2000
SESSION_DELTA_TURN_THRESHOLD = 4
SESSION_DELTA_SECONDS_THRESHOLD = 180


@dataclass
class SessionMemoryState:
    """当前 session 的抽取状态。"""

    session_id: str
    extracted_once: bool = False
    last_extracted_tokens: int = 0
    last_extracted_turns: int = 0
    last_extracted_ts: float = 0.0
    in_flight: bool = False


def build_session_memory_state(session_id: Optional[str] = None) -> SessionMemoryState:
    sid = str(session_id or "").strip() or uuid.uuid4().hex[:12]
    return SessionMemoryState(session_id=sid)


def _to_int(value, default_value: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default_value


def _thresholds(config: dict) -> tuple[int, int, int, int]:
    first_token = _to_int(
        config.get("session_memory_first_extract_tokens", SESSION_FIRST_EXTRACT_TOKEN_THRESHOLD),
        SESSION_FIRST_EXTRACT_TOKEN_THRESHOLD,
    )
    delta_token = _to_int(
        config.get("session_memory_delta_tokens", SESSION_DELTA_TOKEN_THRESHOLD),
        SESSION_DELTA_TOKEN_THRESHOLD,
    )
    delta_turn = _to_int(
        config.get("session_memory_delta_turns", SESSION_DELTA_TURN_THRESHOLD),
        SESSION_DELTA_TURN_THRESHOLD,
    )
    delta_seconds = _to_int(
        config.get("session_memory_delta_seconds", SESSION_DELTA_SECONDS_THRESHOLD),
        SESSION_DELTA_SECONDS_THRESHOLD,
    )
    return max(1, first_token), max(1, delta_token), max(1, delta_turn), max(1, delta_seconds)


def should_extract_memory(
    *,
    token_count: int,
    turn_count: int,
    state: SessionMemoryState,
    config: dict,
) -> bool:
    """是否应该触发 session memory 抽取。"""
    if state.in_flight:
        return False

    first_token, delta_token, delta_turn, delta_seconds = _thresholds(config)
    if token_count < first_token:
        return False

    if not state.extracted_once:
        return True

    now = time.time()
    return (
        token_count - state.last_extracted_tokens >= delta_token
        and turn_count - state.last_extracted_turns >= delta_turn
        and now - state.last_extracted_ts >= delta_seconds
    )


def get_session_summary_file(session_id: str, cwd: Path | None = None) -> Path:
    """返回当前启动会话的 summary 文件路径（懒创建，不在此处落盘）。"""
    base = get_project_memory_dir(cwd)
    sid = str(session_id or "").strip() or "default_session"
    return base / "sessions" / sid / "summary.md"


def _build_session_summary_prompt(messages: list[dict], token_count: int) -> list[dict]:
    recent = messages[-16:] if len(messages) > 16 else messages
    serialized = []
    for m in recent:
        role = str(m.get("role", ""))
        if role not in ("system", "user", "assistant"):
            continue
        content = str(m.get("content", ""))
        if content:
            serialized.append(f"[{role}] {content}")
    transcript = "\n".join(serialized)

    system = (
        "你是 session 记忆压缩器。"
        "请把当前长对话提炼成增量摘要，写给后续轮次复用。\n"
        "输出要求：\n"
        "1) 4-8 条要点；\n"
        "2) 只保留稳定偏好、关键决策、约束与未完成事项；\n"
        "3) 不要复述寒暄；\n"
        "4) 直接输出 Markdown 列表。"
    )
    user = (
        f"当前累计 token 约: {token_count}\n"
        "以下是最近对话片段，请做增量总结：\n\n"
        f"{transcript}"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


async def _write_session_summary_async(
    *,
    llm,
    messages: list[dict],
    token_count: int,
    turn_count: int,
    state: SessionMemoryState,
) -> bool:
    prompt = _build_session_summary_prompt(messages, token_count)
    summary = await asyncio.to_thread(llm.invoke, prompt)
    summary = str(summary or "").strip()
    if not summary or summary.startswith("❌ API 错误"):
        return False

    target = get_session_summary_file(state.session_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        target.write_text("# Session Summary\n\n", encoding="utf-8")

    now_text = datetime.now().isoformat(timespec="seconds")
    block = (
        f"\n## {now_text}\n"
        f"token_count: {token_count}\n"
        f"turn_count: {turn_count}\n"
        f"{summary}\n"
    )
    await asyncio.to_thread(append_text_with_lock, target, block)

    state.extracted_once = True
    state.last_extracted_tokens = token_count
    state.last_extracted_turns = turn_count
    state.last_extracted_ts = time.time()
    return True


def schedule_session_memory_extract(
    *,
    llm,
    messages: list[dict],
    token_count: int,
    turn_count: int,
    state: SessionMemoryState,
) -> Optional[threading.Thread]:
    """按阈值调度一次 session memory 抽取。"""
    if not getattr(llm, "config", {}).get("api_key"):
        return None

    if not should_extract_memory(
        token_count=token_count,
        turn_count=turn_count,
        state=state,
        config=getattr(llm, "config", {}),
    ):
        return None

    state.in_flight = True
    snapshot = [dict(m) for m in messages]

    def _runner() -> None:
        try:
            asyncio.run(
                _write_session_summary_async(
                    llm=llm,
                    messages=snapshot,
                    token_count=token_count,
                    turn_count=turn_count,
                    state=state,
                )
            )
        except Exception:
            # 失败静默；不更新提取状态，下一轮满足阈值后可再尝试。
            pass
        finally:
            state.in_flight = False

    t = threading.Thread(target=_runner, name="session-memory-writer", daemon=True)
    t.start()
    return t
