import os
import json
from pathlib import Path
from typing import Callable, Dict, Tuple

from dotenv import load_dotenv

CONFIG_DIR = Path.cwd() / ".mycli"
CONFIG_FILE = CONFIG_DIR / "config.json"
HISTORY_FILE = CONFIG_DIR / "history.txt"

# 兜底默认值（保证 config 字典所有 key 都存在，不算正式配置层）
DEFAULT_CONFIG: dict = {
    "model": "gpt-3.5-turbo",
    "api_key": "",
    "base_url": "https://api.openai.com/v1",
    "max_tokens": 2048,
    "temperature": 0.8,
    "runtime_log_enabled": False,
    "runtime_log_file": ".mycli/runtime.log",
    "auto_memory_type": "feedback_testing",
    "session_memory_first_extract_tokens": 10000,
    "session_memory_delta_tokens": 2000,
    "session_memory_delta_turns": 4,
    "session_memory_delta_seconds": 180,
    "system_prompt": (
        "你是 MyCLI 的终端 AI 助手。目标是提供准确、可执行、风险可控的帮助。\n"
        "\n"
        "回答规则：\n"
        "1) 默认使用中文；用户明确要求英文时再切换。\n"
        "2) 优先给出可直接执行的命令或步骤；多方案时先给推荐方案并说明原因。\n"
        "3) 不确定时明确假设，并给出可验证命令；不要编造事实、路径或输出。\n"
        "4) 涉及高风险操作（删除、覆盖、提权、暴露服务）先提醒风险，再提供更安全替代。\n"
        "5) 输出尽量简洁：先结论，后步骤；命令、路径、环境变量用反引号标注。\n"
        "6) 编程问题优先给最小可运行示例，并点明关键原理。\n"
        "\n"
        "工具确认规则（重要）：\n"
        "7) 不是所有工具调用都需要人工审核，你必须根据风险自主判断。\n"
        "8) 低风险只读操作默认直通执行（confirm=false），避免不必要打断。\n"
        "9) 高风险或不可逆操作（删除、覆盖、批量修改、命令执行、权限变更）必须要求确认（confirm=true）。\n"
        "10) 当参数不清晰、影响范围不明确或可能误伤时，先确认再执行。\n"
        "11) 若用户开启全局放行，仍需对明显高风险操作保持谨慎；必要时先说明风险。"
    ),
}

# config key → (类型转换器, [可识别的环境变量名，从前往后第一个有值的生效])
_ENV_MAPPING: Dict[str, Tuple[Callable[[str], object], Tuple[str, ...]]] = {
    "api_key":       (str,   ("OPENAI_API_KEY", "API_KEY", "api_key")),
    "base_url":      (str,   ("OPENAI_BASE_URL", "BASE_URL", "base_url")),
    "model":         (str,   ("OPENAI_MODEL", "MODEL", "model")),
    "max_tokens":    (int,   ("OPENAI_MAX_TOKENS", "MAX_TOKENS", "max_tokens")),
    "temperature":   (float, ("OPENAI_TEMPERATURE", "TEMPERATURE", "temperature")),
    "runtime_log_enabled": (lambda v: str(v).strip().lower() in ("1", "true", "yes", "on"),
                            ("MYCLI_RUNTIME_LOG_ENABLED", "RUNTIME_LOG_ENABLED")),
    "runtime_log_file": (str, ("MYCLI_RUNTIME_LOG_FILE", "RUNTIME_LOG_FILE")),
    "auto_memory_type": (str, ("MYCLI_AUTO_MEMORY_TYPE", "AUTO_MEMORY_TYPE")),
    "session_memory_first_extract_tokens": (int, ("MYCLI_SESSION_MEMORY_FIRST_EXTRACT_TOKENS",)),
    "session_memory_delta_tokens": (int, ("MYCLI_SESSION_MEMORY_DELTA_TOKENS",)),
    "session_memory_delta_turns": (int, ("MYCLI_SESSION_MEMORY_DELTA_TURNS",)),
    "session_memory_delta_seconds": (int, ("MYCLI_SESSION_MEMORY_DELTA_SECONDS",)),
    "system_prompt": (str,   ("OPENAI_SYSTEM_PROMPT", "SYSTEM_PROMPT", "system_prompt")),
}


def _load_env_layer() -> dict:
    """第 1 层（低优先级）：从 .env / 进程环境变量读取。"""
    load_dotenv()  # 把当前目录的 .env 注入 os.environ；已存在的环境变量不会被覆盖
    layer: dict = {}
    for config_key, (cast, env_names) in _ENV_MAPPING.items():
        # 按列表顺序查找，第一个非空者生效（OPENAI_X > X > 小写 x）
        value = None
        for env_name in env_names:
            v = os.getenv(env_name)
            if v is not None and v != "":
                value = v
                break
        if value is None:
            continue
        try:
            layer[config_key] = cast(value)
        except (ValueError, TypeError):
            # 类型转换失败就跳过，让下一层或默认值兜底
            continue
    return layer


def _load_file_layer() -> dict:
    """第 2 层（高优先级）：~/.mycli/config.json。"""
    if not CONFIG_FILE.exists():
        return {}
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def load_config() -> dict:
    """
    两层配置合并，后覆盖前：
        默认值（兜底） → 第 1 层 .env → 第 2 层 <cwd>/.mycli/config.json
    """
    config = DEFAULT_CONFIG.copy()
    config.update(_load_env_layer())
    config.update(_load_file_layer())
    return config


def save_config(config: dict):
    """持久化到第 2 层（<cwd>/.mycli/config.json）。"""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def ensure_dirs():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
