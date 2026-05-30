import os
import json
from pathlib import Path
from typing import Callable, Dict, Tuple

from dotenv import load_dotenv

CONFIG_DIR = Path.home() / ".mycli"
CONFIG_FILE = CONFIG_DIR / "config.json"
HISTORY_FILE = CONFIG_DIR / "history.txt"

# 兜底默认值（保证 config 字典所有 key 都存在，不算正式配置层）
DEFAULT_CONFIG: dict = {
    "model": "gpt-3.5-turbo",
    "api_key": "",
    "base_url": "https://api.openai.com/v1",
    "max_tokens": 2048,
    "temperature": 0.8,
    "system_prompt": "你是一个有用的终端助手，擅长回答编程和系统管理问题。请用简洁的方式回答。",
}

# .env 变量名 → (config key, 类型转换器)
_ENV_MAPPING: Dict[str, Tuple[str, Callable[[str], object]]] = {
    "OPENAI_API_KEY": ("api_key", str),
    "OPENAI_BASE_URL": ("base_url", str),
    "OPENAI_MODEL": ("model", str),
    "OPENAI_MAX_TOKENS": ("max_tokens", int),
    "OPENAI_TEMPERATURE": ("temperature", float),
    "OPENAI_SYSTEM_PROMPT": ("system_prompt", str),
}


def _load_env_layer() -> dict:
    """第 1 层（低优先级）：从 .env / 进程环境变量读取。"""
    load_dotenv()  # 把当前目录的 .env 注入 os.environ；已存在的环境变量不会被覆盖
    layer: dict = {}
    for env_key, (config_key, cast) in _ENV_MAPPING.items():
        value = os.getenv(env_key)
        if value is None or value == "":
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
