from prompt_toolkit.completion import Completer, Completion


COMMANDS = {
    "/help": "显示帮助信息",
    "/clear": "清空对话历史",
    "/config": "查看当前配置",
    "/allow": "授权控制（/allow all 跳过命令执行确认）",
    "/chat": "切回普通聊天模式（LLM 直接对话）",
    "/normal": "切回普通聊天模式（同 /chat）",
    "/model": "切换模型（如 /model gpt-4）",
    "/system": "设置系统提示词",
    "/history": "查看对话历史",
    "/react": "切换到 ReAct 模式（/react 或 /react <问题>）",
    "/exit": "退出程序",
}


class CliCompleter(Completer):
    def get_completions(self, document, complete_event):
        text = document.text_before_cursor.strip()
        if text.startswith("/"):
            for cmd, desc in COMMANDS.items():
                if cmd.startswith(text):
                    yield Completion(
                        cmd,
                        start_position=-len(text),
                        display_meta=desc,
                    )
