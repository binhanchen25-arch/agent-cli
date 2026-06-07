"""运行日志模块：基于标准库 logging 输出 JSONL。"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

_LOCK = threading.Lock()
_LOGGER_CACHE: Dict[str, logging.Logger] = {}
_SECRET_KEYS = ("key", "token", "password", "secret", "authorization")


def is_runtime_log_enabled(config: dict) -> bool:
    return bool(config.get("runtime_log_enabled", False))


def get_log_file_path(config: dict) -> Path:
    configured = str(config.get("runtime_log_file", ".mycli/runtime.log")).strip()
    return Path(configured or ".mycli/runtime.log")


def _sanitize_value(field_name: str, value: Any) -> Any:
    key = field_name.lower()
    if any(token in key for token in _SECRET_KEYS):
        return "***"
    if isinstance(value, str):
        if len(value) > 1000:
            return value[:1000] + "...<truncated>"
        return value
    if isinstance(value, dict):
        return {str(k): _sanitize_value(str(k), v) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize_value(field_name, v) for v in value]
    return value


def _sanitize_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {k: _sanitize_value(k, v) for k, v in payload.items()}


def _get_logger(config: dict) -> logging.Logger:
    log_path = get_log_file_path(config)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    cache_key = str(log_path.resolve())

    with _LOCK:
        logger = _LOGGER_CACHE.get(cache_key)
        if logger is not None:
            return logger

        logger = logging.getLogger(f"mycli.runtime.{cache_key}")
        logger.setLevel(logging.INFO)
        logger.propagate = False

        handler = logging.FileHandler(log_path, encoding="utf-8")
        handler.setLevel(logging.INFO)
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.handlers = [handler]

        _LOGGER_CACHE[cache_key] = logger
        return logger


def log_event(config: dict, event: str, **payload: Any) -> None:
    """写一条运行日志（JSONL）。未开启时直接返回。"""
    if not is_runtime_log_enabled(config):
        return

    record: Dict[str, Any] = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "event": event,
    }
    record.update(_sanitize_payload(payload))

    try:
        logger = _get_logger(config)
        logger.info(json.dumps(record, ensure_ascii=False, default=str))
    except Exception:
        # 日志系统失败不能影响主流程
        return
