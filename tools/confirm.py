"""工具执行确认：统一的全局默认开关 + 每次调用参数覆盖。"""

from __future__ import annotations

import sys

from cli.renderer import console

# 默认策略：当模型未显式给出 confirm 时，是否需要人工确认。
# False = 把决策权交给模型；模型不传就直接放行（查询类工具自然不再被打断）。
# True  = 模型不传时仍兜底询问（更保守）。
# 可被 `/allow` 命令修改。
_DEFAULT_TOOL_CONFIRM = False
_CONFIRM_PARAM_KEY = "confirm"


def set_default_tool_confirm(enabled: bool) -> None:
    """设置工具调用默认是否需要人工确认。"""
    global _DEFAULT_TOOL_CONFIRM
    _DEFAULT_TOOL_CONFIRM = bool(enabled)


def get_default_tool_confirm() -> bool:
    """读取工具调用默认是否需要人工确认。"""
    return _DEFAULT_TOOL_CONFIRM


def _to_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in ("1", "true", "yes", "y", "on"):
            return True
        if normalized in ("0", "false", "no", "n", "off"):
            return False
    return None


def should_confirm_tool_call(parameters: dict) -> bool:
    """计算本次工具调用是否需要确认。

    决策顺序：
        1. 模型显式传入 confirm=true/false → 完全听模型的。
        2. 模型没传 → 走全局默认（默认为 False，即直接放行）。
    """
    raw = parameters.get(_CONFIRM_PARAM_KEY, None)
    parsed = _to_bool(raw)
    if parsed is None:
        return get_default_tool_confirm()
    return parsed


def strip_confirm_parameter(parameters: dict) -> dict:
    """移除框架级 confirm 参数，避免干扰工具本身参数解析。"""
    if _CONFIRM_PARAM_KEY not in parameters:
        return parameters
    cleaned = dict(parameters)
    cleaned.pop(_CONFIRM_PARAM_KEY, None)
    return cleaned


def is_confirm_explicitly_set(parameters: dict) -> bool:
    """模型是否显式传入了 confirm 字段（用于区分"未传"和"传 False"）。"""
    return _CONFIRM_PARAM_KEY in parameters


def confirm_in_cli(detail: str) -> bool:
    """终端弹窗确认：用方向键 / Tab 选择 Yes / No，回车确认。

    - 在 TTY 终端会用 prompt_toolkit 的 yes_no_dialog 渲染带按钮的弹窗。
    - 非 TTY（管道、CI、被重定向）环境自动降级为输入式 yes/no，避免卡死。
    - Ctrl-C / EOF 视为拒绝。
    """
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return _confirm_via_stdin(detail)

    # 弹窗前先让 Rich 的 Live 渲染（如 spinner、流式 Markdown）让位，
    # 否则两个全屏控件会互相抢屏导致闪烁或黑屏。
    try:
        from prompt_toolkit.shortcuts import yes_no_dialog
    except ImportError:
        return _confirm_via_stdin(detail)

    try:
        result = yes_no_dialog(
            title="确认执行该操作？",
            text=detail,
            yes_text="Yes",
            no_text="No",
        ).run()
    except (KeyboardInterrupt, EOFError):
        result = False
    return bool(result)


def _confirm_via_stdin(detail: str) -> bool:
    """无 TTY 时的兜底：纯文本 yes/no。"""
    console.print(
        f"[bold yellow]确认执行该操作？[/bold yellow]\n{detail}", highlight=False
    )
    try:
        answer = input("输入 yes/y 或 no/n > ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        return False
    return answer in ("yes", "y", "1", "true")


# 兼容旧接口名（历史代码仍可能引用）。
def set_allow_all_windows_cmd(enabled: bool) -> None:
    """兼容旧名称：enabled=True 表示全局放行（不确认）。"""
    set_default_tool_confirm(not bool(enabled))


def get_allow_all_windows_cmd() -> bool:
    """兼容旧名称：返回是否全局放行（不确认）。"""
    return not get_default_tool_confirm()
