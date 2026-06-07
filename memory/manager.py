"""CLI 级 memory 目录管理。"""

from __future__ import annotations

import re
import threading
from pathlib import Path
from typing import Dict

MEMORY_FILE_MAP: Dict[str, str] = {
    "user_role": "user_role.md",
    "feedback_testing": "feedback_testing.md",
    "project_auth_rewrite": "project_auth_rewrite.md",
}

_DEFAULT_CONTENT: Dict[str, str] = {
    "user_role.md": "# 用户角色记忆\n\n",
    "feedback_testing.md": "# 反馈记忆：测试偏好\n\n",
    "project_auth_rewrite.md": "# 项目记忆：认证重构背景\n\n",
}

_MEMORY_RW_LOCK = threading.Lock()
_TOOL_MEMORY_WRITE_MARKED = False


def _sanitize_segment(segment: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", segment.strip())
    return cleaned or "_"


def _project_key_from_cwd(cwd: Path) -> str:
    """把 cwd 归一成单个字符串 key（不拆多级目录）。"""
    resolved = str(cwd.resolve())
    # 路径分隔符统一替换为双下划线，避免在 projects 下产生层级。
    normalized = resolved.replace("\\", "__").replace("/", "__")
    return _sanitize_segment(normalized) or "default_project"


def get_project_memory_dir(cwd: Path | None = None) -> Path:
    """返回 ~/.mycli/projects/<cwd>/memory 路径（跨平台）。"""
    current = Path.cwd() if cwd is None else Path(cwd)
    project_key = _project_key_from_cwd(current)
    return Path.home() / ".mycli" / "projects" / project_key / "memory"


def ensure_cli_memory_structure(cwd: Path | None = None) -> Path:
    """确保 memory 目录与默认记忆文件存在。"""
    memory_dir = get_project_memory_dir(cwd)
    memory_dir.mkdir(parents=True, exist_ok=True)

    for filename, template in _DEFAULT_CONTENT.items():
        target = memory_dir / filename
        if not target.exists():
            target.write_text(template, encoding="utf-8")

    return memory_dir


def get_auto_memory_file(memory_type: str = "feedback_testing") -> Path:
    """自动记忆写入文件：~/cli/<type>.md。"""
    root = Path.home() / "cli"
    root.mkdir(parents=True, exist_ok=True)
    key = str(memory_type or "").strip().lower()
    filename = MEMORY_FILE_MAP.get(key, "auto_memory.md")
    target = root / filename
    if not target.exists():
        target.write_text("# 自动记忆\n\n", encoding="utf-8")
    return target


def resolve_memory_file(memory_type: str, cwd: Path | None = None) -> Path:
    """将 type 参数映射到 memory 文件路径。"""
    key = str(memory_type or "").strip().lower()
    if key in MEMORY_FILE_MAP:
        filename = MEMORY_FILE_MAP[key]
    elif key in MEMORY_FILE_MAP.values():
        filename = key
    else:
        allowed = ", ".join(sorted(MEMORY_FILE_MAP.keys()))
        raise ValueError(f"memory type 不支持: {memory_type}。可用值: {allowed}")

    memory_dir = ensure_cli_memory_structure(cwd)
    return memory_dir / filename


def mark_memory_written_by_tool() -> None:
    """标记本轮已通过 memory 工具写入，自动记忆应跳过。"""
    global _TOOL_MEMORY_WRITE_MARKED
    with _MEMORY_RW_LOCK:
        _TOOL_MEMORY_WRITE_MARKED = True


def reset_memory_write_marker() -> None:
    """开始新一轮回答前重置标记。"""
    global _TOOL_MEMORY_WRITE_MARKED
    with _MEMORY_RW_LOCK:
        _TOOL_MEMORY_WRITE_MARKED = False


def consume_memory_write_marker() -> bool:
    """消费并清空标记。True 表示本轮已有工具写记忆。"""
    global _TOOL_MEMORY_WRITE_MARKED
    with _MEMORY_RW_LOCK:
        marked = _TOOL_MEMORY_WRITE_MARKED
        _TOOL_MEMORY_WRITE_MARKED = False
    return marked


def read_text_with_lock(path: Path) -> str:
    with _MEMORY_RW_LOCK:
        return path.read_text(encoding="utf-8")


def append_text_with_lock(path: Path, content: str) -> None:
    with _MEMORY_RW_LOCK:
        with open(path, "a", encoding="utf-8") as f:
            f.write(content)
