# 🤖 MyCLI - 终端 AI 助手

一个 Copilot 风格的终端 AI 助手，支持普通聊天和 ReAct 智能体模式，可调用工具完成复杂任务。

## ✨ 功能特性

- 💬 **流式对话** — 实时 Markdown 渲染，支持 OpenAI 兼容 API
- 🧠 **ReAct 智能体** — 多步推理 + 工具调用，自动拆解任务
- 🔧 **可扩展工具** — 内置 echo、now、命令执行工具，支持自定义扩展
- 🎨 **Rich 终端 UI** — Markdown 面板、配置表格、Spinner 动画
- ⌨️ **命令补全** — 斜杠命令自动补全
- 🔒 **命令确认** — 工具执行前需用户确认，可通过 `/allow` 跳过
- 🎭 **演示模式** — 无 API Key 时自动使用模拟回复

## 📦 安装

### 从源码运行

```bash
# 克隆仓库
git clone https://github.com/your-username/mycli.git
cd mycli

# 安装依赖
pip install -r requirements.txt

# 运行
python main.py
```

### 打包为可执行文件

```bash
pip install pyinstaller
pyinstaller --onefile --name mycli main.py
# 生成 dist/mycli（或 dist/mycli.exe）
```

## ⚙️ 配置

支持三种配置方式（优先级从高到低）：

### 1. 环境变量

```bash
export OPENAI_API_KEY=sk-your-key
export OPENAI_BASE_URL=https://api.openai.com/v1
export model=gpt-4o
export temperature=0.8
```

### 2. `.env` 文件

在项目根目录创建 `.env` 文件：

```env
OPENAI_API_KEY=sk-your-key
OPENAI_BASE_URL=https://api.openai.com/v1
model=gpt-4o
```

### 3. 配置文件

自动生成于 `~/.mycli/config.json`，也可通过应用内命令修改：

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

## 🚀 使用

启动后直接输入问题即可对话，或使用斜杠命令：

| 命令 | 说明 |
|------|------|
| `/help` | 显示帮助信息 |
| `/clear` | 清空对话历史 |
| `/config` | 查看当前配置 |
| `/model <name>` | 切换模型 |
| `/system <prompt>` | 设置系统提示词 |
| `/history` | 查看对话历史 |
| `/react` | 切换到 ReAct 智能体模式 |
| `/react <问题>` | 直接用 ReAct 执行一次任务 |
| `/allow` | 跳过工具执行确认 |
| `/allow off` | 恢复工具执行确认 |
| `/chat` | 切回普通聊天模式 |
| `/exit` | 退出程序 |

### ReAct 模式示例

```
❯ /react 当前时间是几点
🤔 Thinking… (step 1/8)
# Agent 自动调用 now 工具获取时间，返回结果
```

## 📁 项目结构

```
main.py              # 入口
core/
  config.py          # 配置管理（环境变量 + 配置文件）
  llm.py             # OpenAI 兼容 API 封装（流式/非流式）
  reagent.py         # ReAct 智能体（推理 + 行动循环）
cli/
  app.py             # 主应用（命令处理 + 对话循环）
  completer.py       # 斜杠命令自动补全
  renderer.py        # Rich 终端渲染
tools/
  base.py            # 工具抽象基类 + @tool_action 装饰器
  builtin.py         # 内置工具（echo / now / 命令执行）
  registry.py        # 工具注册表
test/
  test_cli_app.py    # 单元测试
```

## 🔧 自定义工具

继承 `Tool` 基类即可添加新工具：

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

然后在 `builtin.py` 的 `default_tool_registry()` 中注册即可。

## 📄 License

MIT
