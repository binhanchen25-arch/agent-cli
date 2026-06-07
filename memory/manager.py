"""CLI 级 memory 目录管理。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List

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


def _sanitize_segment(segment: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", segment.strip())
    return cleaned or "_"


def _project_parts_from_cwd(cwd: Path) -> List[str]:
    resolved = cwd.resolve()

    parts: List[str] = []
    drive = resolved.drive.rstrip(":\\/")
    if drive:
        parts.append(_sanitize_segment(drive))

    for part in resolved.parts:
        if part in ("/", "\\"):
            continue
        if part == resolved.drive:
            continue
        parts.append(_sanitize_segment(part))

    return parts or ["default_project"]


def get_project_memory_dir(cwd: Path | None = None) -> Path:
    """返回 ~/.claude/projects/<cwd>/memory 路径（跨平台）。"""
    current = Path.cwd() if cwd is None else Path(cwd)
    project_parts = _project_parts_from_cwd(current)
    return Path.home() / ".claude" / "projects" / Path(*project_parts) / "memory"


def ensure_cli_memory_structure(cwd: Path | None = None) -> Path:
    """确保 memory 目录与默认记忆文件存在。"""
    memory_dir = get_project_memory_dir(cwd)
    memory_dir.mkdir(parents=True, exist_ok=True)

    for filename, template in _DEFAULT_CONTENT.items():
        target = memory_dir / filename
        if not target.exists():
            target.write_text(template, encoding="utf-8")

    return memory_dir


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
