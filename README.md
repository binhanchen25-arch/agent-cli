# MyCLI

> 终端原生的 AI 助手 —— 流式对话 + ReAct 智能体 + 可扩展工具与钩子。

MyCLI 是一个运行在终端中的 OpenAI 兼容 AI 客户端，提供两种交互模式：

- **聊天模式** —— 与 LLM 直接流式对话，Markdown 实时渲染
- **ReAct 智能体模式** —— 基于 OpenAI Function Calling 的多步推理与工具调用，自动拆解任务

配置体系采用 `.env` + `<cwd>/.mycli/` 的分层模型，并支持通过 `hooks.py` 注入用户自定义回调，无需修改源码即可扩展行为。

---

## 目录

- [核心特性](#核心特性)
- [快速开始](#快速开始)
- [环境要求](#环境要求)
- [配置](#配置)
- [命令参考](#命令参考)
- [用户钩子](#用户钩子)
- [项目结构](#项目结构)
- [扩展开发](#扩展开发)
- [测试](#测试)
- [License](#license)

---

## 核心特性

| 类别 | 能力 |
|------|------|
| 对话 | 流式 Markdown 渲染、对话历史、多轮上下文管理 |
| 智能体 | ReAct 多步推理、并行工具调用、命令执行确认机制 |
| 配置 | 分层加载（默认 / `.env` / `.mycli/config.json`）、项目本地隔离 |
| 扩展 | `Tool` 抽象基类、`@tool_action` 子工具装饰器、用户 hooks 热重载 |
| 终端 UX | Rich 主题、Spinner、斜杠命令自动补全、备用屏幕缓冲区 |
| 兜底 | 无 API Key 时自动进入演示模式，便于试用 |

---

## 快速开始

```bash
# 1. 克隆
git clone https://github.com/your-username/mycli.git
cd mycli

# 2. 安装依赖
pip install -r requirements.txt

# 3. 配置 API Key（任选其一）
echo "OPENAI_API_KEY=sk-xxx" > .env

# 4. 启动
python main.py
```

进入 REPL 后可直接对话，或输入 `/help` 查看命令；输入 `/react <问题>` 触发智能体模式。

### 打包为单文件可执行程序

```bash
pip install pyinstaller
pyinstaller --onefile --name mycli main.py
# 产物位于 dist/mycli（Windows 为 dist/mycli.exe）
```

---

## 环境要求

- Python **3.10+**
- 依赖（见 [requirements.txt](requirements.txt)）：
  - `openai >= 1.0.0`
  - `rich >= 13.0.0`
  - `prompt_toolkit >= 3.0.0`
  - `python-dotenv >= 1.0.0`
  - `pydantic >= 2.0.0`

---

## 配置

MyCLI 采用**两层配置模型**，后者覆盖前者：

```
默认值（兜底）  →  第 1 层 .env  →  第 2 层 <cwd>/.mycli/config.json
```

所有配置文件均位于启动 CLI 时的**当前工作目录**（与 `.env`、`.git` 行为一致），不同项目可拥有各自独立的配置、历史与钩子。

### 第 1 层：`.env`（推荐放敏感信息）

```env
OPENAI_API_KEY=sk-your-key
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o
OPENAI_TEMPERATURE=0.8
OPENAI_MAX_TOKENS=2048
OPENAI_SYSTEM_PROMPT=你是一个有用的终端助手
```

进程环境变量与 `.env` 同优先级 —— `load_dotenv()` 不会覆盖已存在的环境变量。

### 第 2 层：`<cwd>/.mycli/config.json`（推荐放项目偏好）

应用内通过 `/apikey`、`/model`、`/temperature` 等命令修改时会持久化到此文件：

```json
{
  "api_key": "sk-your-key",
  "base_url": "https://api.openai.com/v1",
  "model": "gpt-4o",
  "max_tokens": 2048,
  "temperature": 0.8,
  "system_prompt": "你是一个有用的终端助手"
}
```

> **推荐实践**：`api_key` 放 `.env` 并加入 `.gitignore`；项目级偏好（模型、温度、系统提示词）放 `config.json` 入 git。

完整字段含义见 [core/config.py](core/config.py) 中的 `DEFAULT_CONFIG` 与 `_ENV_MAPPING`。

---

## 命令参考

| 命令 | 说明 |
|------|------|
| `/help` | 显示帮助 |
| `/clear` | 清空对话历史（保留 system prompt） |
| `/history` | 查看当前会话历史 |
| `/config` | 以表格形式展示当前配置 |
| `/model <name>` | 查看 / 切换模型 |
| `/apikey <key>` | 查看 / 设置 API Key |
| `/base_url <url>` | 查看 / 设置 API Base URL |
| `/temperature <0–2>` | 查看 / 设置采样温度 |
| `/max_tokens <int>` | 查看 / 设置最大输出 token |
| `/system <prompt>` | 查看 / 设置系统提示词 |
| `/react` | 切换至 ReAct 智能体模式 |
| `/react <问题>` | 切换并立即执行一次任务 |
| `/chat` / `/normal` | 切回普通聊天模式 |
| `/allow` / `/allow all` | 跳过命令执行确认（**危险**） |
| `/allow off` | 恢复命令执行确认 |
| `/exit` | 退出程序 |

### ReAct 模式示例

```
❯ /react 列出当前目录的 Python 文件
🤔 Thinking… (step 1/20)
🔧 Running: glob (1 calls)
# Agent 自动调用 glob 工具，将结果汇总后返回最终答案
```

---

## 用户钩子

在项目的 `<cwd>/.mycli/hooks.py` 中按约定名称定义函数，MyCLI 会**动态加载**，文件修改后**立即生效**（基于 mtime 的热重载，无需重启）。

### 支持的钩子

| 函数名 | 触发时机 | 签名 |
|--------|---------|------|
| `before_step` | `ReActAgent` 每次调用 LLM 之前 | `(step: int, messages: list[dict]) -> list[dict] \| None` |

**约定**：`before_step` 返回 `None` 表示不修改 `messages`；返回 `list` 则用其替换。典型用途包括日志记录、上下文裁剪、提示词注入等。

### 最小示例

```python
# .mycli/hooks.py
import json
from pathlib import Path

LOG_FILE = Path(__file__).parent / "agent.log"

def before_step(step, messages):
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"\n=== step {step} ===\n")
        f.write(json.dumps(messages, ensure_ascii=False, indent=2))
    return None  # 不修改 messages
```

### 完整示例

仓库附带的 [.mycli/hooks.py](.mycli/hooks.py) 演示了三种常见行为：

1. **日志记录** —— 将每步 messages dump 到 `.mycli/agent.log`
2. **上下文裁剪** —— 超过阈值时只保留 system 消息 + 最近 N 条
3. **提示词注入** —— 可选地在每步追加额外的 system 提醒

> 钩子加载器的实现见 [core/hooks.py](core/hooks.py)；用户钩子抛出的异常会被捕获并打印警告，不会影响主流程。

---

## 项目结构

```
.
├── main.py                  # 入口：构造并运行 ChatApp
├── requirements.txt
├── core/
│   ├── config.py            # 两层配置加载（.env + .mycli/config.json）
│   ├── llm.py               # OpenAI 兼容客户端（流式 / 非流式 / Function Calling）
│   ├── reagent.py           # ReActAgent + ReActChatLLM 适配器
│   └── hooks.py             # 用户钩子动态加载器（mtime 热重载）
├── cli/
│   ├── app.py               # ChatApp：REPL、命令分发、对话循环
│   ├── completer.py         # 斜杠命令自动补全
│   └── renderer.py          # Rich 终端渲染与流式输出
├── tools/
│   ├── base.py              # Tool 抽象基类 + ToolParameter + @tool_action
│   ├── registry.py          # ToolRegistry：查找、schema、执行
│   └── builtin.py           # 内置工具集（echo / now / tree / glob / grep / view / 命令执行）
├── .mycli/                  # 项目本地配置目录（位于启动 CLI 时的 cwd 下）
│   ├── config.json          # 第 2 层配置
│   ├── hooks.py             # 用户钩子
│   ├── history.txt          # 输入历史
│   └── agent.log            # （示例 hook 产生）每步 messages 日志
└── test/
    └── test_cli_app.py      # 单元测试
```

### 架构要点

- **LLM 接口契约** —— 任何用作 `ChatApp.llm` 的对象都需提供 `stream(messages)` 与 `invoke(messages)`。`ReActChatLLM` 将 `ReActAgent` 适配到该契约，使聊天与智能体模式可以透明切换。
- **工具系统** —— `Tool` 子类通过 `get_parameters()` 声明 JSON Schema，由 `ToolRegistry` 自动生成 OpenAI Function Calling schema 并分发执行。
- **危险操作隔离** —— 命令执行工具默认要求用户确认；拒绝时通过 `UserRefusedError` 让 Agent 优雅回退到 `_finish_on_refused()`。

---

## 扩展开发

### 添加新工具

```python
from tools.base import Tool, ToolParameter

class MyTool(Tool):
    def __init__(self):
        super().__init__(name="mytool", description="我的工具")

    def get_parameters(self):
        return [ToolParameter(name="input", type="string", description="输入参数")]

    def run(self, parameters):
        return f"结果: {parameters['input']}"
```

在 [tools/builtin.py](tools/builtin.py) 的 `default_tool_registry()` 中注册即可被 Agent 调用。

### 子工具（expandable tool）

将基类 `expandable=True`，并用 `@tool_action` 装饰方法 —— 框架会根据类型注解与 docstring 自动生成参数 schema 与子命令。

---

## 测试

```bash
# 运行全部测试
python -m unittest discover -s test -p "test_*.py"

# 运行单个测试文件
python -m unittest test.test_cli_app

# 运行单个测试方法
python -m unittest test.test_cli_app.ChatAppTests.test_exit_command_returns_false
```

测试使用 `unittest.mock` 隔离配置、prompt session、LLM 等外部依赖，可在无 API Key、无网络环境下运行。

---

## License

MIT
