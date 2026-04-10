import os
import json
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

CONFIG_DIR = Path.home() / ".mycli"
CONFIG_FILE = CONFIG_DIR / "config.json"
HISTORY_FILE = CONFIG_DIR / "history.txt"

DEFAULT_CONFIG = {
    "model": "gpt-3.5-turbo",
    "api_key": "",
    "base_url": "https://api.openai.com/v1",
    "max_tokens": 2048,
    "temperature": 0.7,
    "system_prompt": "你是一个有用的终端助手，擅长回答编程和系统管理问题。请用简洁的方式回答。",
}


def load_config() -> dict:
    config = DEFAULT_CONFIG.copy()
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            config.update(json.load(f))
    # 环境变量优先
    if os.getenv("OPENAI_API_KEY"):
        config["api_key"] = os.getenv("OPENAI_API_KEY")
    if os.getenv("OPENAI_BASE_URL"):
        config["base_url"] = os.getenv("OPENAI_BASE_URL")
    if os.getenv("model"):
        config["model"] = os.getenv("model")
    if os.getenv("temperature"):
        config["temperature"] = float(os.getenv("temperature"))

    return config


def save_config(config: dict):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def ensure_dirs():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
