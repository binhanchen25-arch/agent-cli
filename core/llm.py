import time
from typing import Generator


def stream_from_openai(messages: list, config: dict) -> Generator[str, None, None]:
    """调用 OpenAI 兼容 API，流式返回文本"""
    try:
        from openai import OpenAI

        client = OpenAI(
            api_key=config["api_key"],
            base_url=config["base_url"],
        )
        response = client.chat.completions.create(
            model=config["model"],
            messages=messages,
            max_tokens=config["max_tokens"],
            temperature=config["temperature"],
            stream=True,
        )
        for chunk in response:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
    except ImportError:
        yield from mock_stream("（未安装 openai 库，使用模拟回复）\n\n")
        yield from mock_stream(f"你说的是: {messages[-1]['content']}")
    except Exception as e:
        yield f"\n❌ API 错误: {e}"


def mock_stream(text: str) -> Generator[str, None, None]:
    """模拟流式输出，用于演示"""
    for char in text:
        yield char
        time.sleep(0.02)


DEMO_RESPONSES = {
    "你好": "你好！👋 我是你的终端助手，有什么可以帮你的？\n\n我可以帮你：\n- 🔧 解答编程问题\n- 📁 生成代码片段\n- 💡 提供技术方案建议\n\n直接输入你的问题就好！",
    "帮助": "## 📖 使用帮助\n\n| 命令 | 说明 |\n|------|------|\n| `/help` | 显示帮助信息 |\n| `/clear` | 清空对话历史 |\n| `/config` | 查看当前配置 |\n| `/model <name>` | 切换模型 |\n| `/exit` | 退出程序 |\n\n直接输入文字即可开始对话。",
}


def demo_stream(user_input: str) -> Generator[str, None, None]:
    """演示模式：不需要 API Key"""
    for key, resp in DEMO_RESPONSES.items():
        if key in user_input:
            yield from mock_stream(resp)
            return

    response = (
        f"收到你的问题：**{user_input}**\n\n"
        "这是演示模式的回复。要连接真实 AI，请配置 API Key：\n\n"
        "```bash\n"
        "export OPENAI_API_KEY=sk-your-key\n"
        "```\n\n"
        "或使用 `/config` 命令设置。"
    )
    yield from mock_stream(response)
