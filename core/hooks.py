"""用户钩子加载器。

允许用户在 `<cwd>/.mycli/hooks.py`（启动 CLI 时所在目录下）里定义回调函数，
运行时被动态加载。支持热重载：文件 mtime 变更后自动重新加载。

约定的 hook 函数（在 hooks.py 中按需定义）：
    before_step(step: int, messages: list[dict]) -> list[dict] | None
        每次 ReActAgent 调用 LLM 之前触发。
        返回 None → 不变；返回 list → 替换 messages。
"""
from __future__ import annotations

import importlib.util
from types import ModuleType
from typing import Callable, Optional

from core.config import CONFIG_DIR

HOOKS_FILE = CONFIG_DIR / "hooks.py"

_cached_module: Optional[ModuleType] = None
_cached_mtime: Optional[float] = None


def load_user_hooks() -> Optional[ModuleType]:
    """加载 `~/.mycli/hooks.py`，文件不存在或加载失败时返回 None。"""
    global _cached_module, _cached_mtime

    if not HOOKS_FILE.exists():
        _cached_module = None
        _cached_mtime = None
        return None

    mtime = HOOKS_FILE.stat().st_mtime
    if _cached_module is not None and _cached_mtime == mtime:
        return _cached_module

    spec = importlib.util.spec_from_file_location("mycli_user_hooks", HOOKS_FILE)
    if spec is None or spec.loader is None:
        return None

    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as e:
        # 不抛出，避免破坏主流程；用 console 提示一次即可
        try:
            from cli.renderer import print_error
            print_error(f"加载 hooks.py 失败: {e}")
        except Exception:
            pass
        return None

    _cached_module = module
    _cached_mtime = mtime
    return module


def get_hook(name: str) -> Optional[Callable]:
    """从用户 hooks.py 中取出一个 callable，不存在则返回 None。"""
    module = load_user_hooks()
    if module is None:
        return None
    fn = getattr(module, name, None)
    return fn if callable(fn) else None
