"""Python 代码执行工具：在隔离命名空间中运行 Python 片段。"""

from __future__ import annotations

import io
import sys
import traceback
from typing import Any, Dict, List

from tools.base import Tool, ToolParameter

_MAX_OUTPUT = 5000  # stdout 最大返回字符数


class PythonReplTool(Tool):
    """在隔离命名空间中执行 Python 代码片段，返回标准输出与结果。"""

    search_hint = "执行 Python 代码片段"

    def __init__(self) -> None:
        super().__init__(
            name="python_repl",
            description=(
                "执行 Python 代码片段并返回标准输出（stdout）。"
                "适合数学计算、数据处理、逻辑验证、格式转换等任务。"
                "每次调用共享同一个命名空间（变量在多次调用间保持）。"
                "不能访问网络，不能操作 GUI。"
            ),
            expandable=False,
        )
        self._namespace: Dict[str, Any] = {}

    def get_parameters(self) -> List[ToolParameter]:
        return [
            ToolParameter(
                name="code",
                type="string",
                description="要执行的 Python 代码字符串。",
                required=True,
            ),
        ]

    def is_destructive(self, parameters=None) -> bool:
        # 任意代码执行无法静态判断副作用，按破坏性对待。
        return True

    def run(self, parameters: Dict[str, Any]) -> str:
        code = str(parameters.get("code", "")).strip()
        if not code:
            return "code 不能为空。"

        stdout_capture = io.StringIO()
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        stderr_capture = io.StringIO()

        try:
            sys.stdout = stdout_capture
            sys.stderr = stderr_capture
            exec(compile(code, "<repl>", "exec"), self._namespace)  # noqa: S102
        except SystemExit:
            return "代码调用了 sys.exit()，已拦截。"
        except Exception:
            tb = traceback.format_exc()
            return f"执行出错:\n{tb}"
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr

        stdout_out = stdout_capture.getvalue()
        stderr_out = stderr_capture.getvalue()

        parts: List[str] = []
        if stdout_out:
            out = stdout_out
            if len(out) > _MAX_OUTPUT:
                out = out[:_MAX_OUTPUT] + f"\n... [输出已截断，共 {len(stdout_out)} 字符]"
            parts.append(out.rstrip())
        if stderr_out:
            parts.append(f"[stderr]\n{stderr_out.rstrip()}")
        if not parts:
            parts.append("（代码执行完毕，无输出）")

        return "\n".join(parts)
