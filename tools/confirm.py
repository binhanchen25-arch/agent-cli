"""工具执行确认：统一的全局默认开关 + 每次调用参数覆盖。"""

from __future__ import annotations

from cli.renderer import console

# 默认策略：当模型未显式给出 confirm 时，是否需要人工确认。
# False = 把决策权交给模型；模型不传就直接放行（查询类工具自然不再被打断）。
# True  = 模型不传时仍兜底询问（更保守）。
# 可被 `\\allow` 命令修改。
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


def confirm_in_cli(detail: str) -> bool:
    """纯命令行确认：输入 yes/y 执行，no/n 取消。"""
    while True:
        answer = console.input(
            f"[bold yellow]确认执行该操作？[/bold yellow]\\n{detail}\\n"
            "输入 [green]yes/y[/green] 或 [red]no/n[/red]\\n> "
        ).strip().lower()
        if answer in ("yes", "y"):
            return True
        if answer in ("no", "n"):
            return False
        console.print("请输入 yes/y 或 no/n。", style="error")


# 兼容旧接口名（历史代码仍可能引用）。
def set_allow_all_windows_cmd(enabled: bool) -> None:
    """兼容旧名称：enabled=True 表示全局放行（不确认）。"""
    set_default_tool_confirm(not bool(enabled))


def get_allow_all_windows_cmd() -> bool:
    """兼容旧名称：返回是否全局放行（不确认）。"""
    return not get_default_tool_confirm()
