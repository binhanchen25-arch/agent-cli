from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.styles import Style

from cli.completer import CliCompleter
from cli.renderer import (
    print_welcome, print_user_message, render_stream,
    print_system, print_error, print_config, clear_screen, console,
    exit_fullscreen, set_terminal_title,
)
import re

from core.config import load_config, save_config, ensure_dirs, HISTORY_FILE
from core.llm import OpenAICompatLLM, demo_stream, stream_text
from core.reagent import ReActAgent

prompt_style = Style.from_dict({
    "prompt": "ansicyan bold",
})


class ChatApp:
    def __init__(self):
        ensure_dirs()
        self.config = load_config()
        self.llm = OpenAICompatLLM(self.config)
        self.messages = []  # 对话历史
        self.use_demo = not self.config.get("api_key")

        if self.config.get("system_prompt"):
            self.messages.append({
                "role": "system",
                "content": self.config["system_prompt"],
            })

        self.session = PromptSession(
            history=FileHistory(str(HISTORY_FILE)),
            completer=CliCompleter(),
            style=prompt_style,
            multiline=False,
        )

    def handle_command(self, cmd: str) -> bool:
        """处理斜杠命令，返回 True 表示继续，False 表示退出"""
        parts = cmd.strip().split(maxsplit=1)
        command = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        if command == "/exit":
            return False
        elif command == "/help":
            self._show_help()
        elif command == "/clear":
            self.messages = self.messages[:1]  # 保留 system prompt
            clear_screen()
            print_system("对话已清空")
        elif command == "/config":
            print_config(self.config)
        elif command == "/model":
            if args:
                self.config["model"] = args
                save_config(self.config)
                print_system(f"模型已切换为: {args}")
            else:
                print_system(f"当前模型: {self.config['model']}")
        elif command == "/system":
            if args:
                self.config["system_prompt"] = args
                self.messages = [{"role": "system", "content": args}]
                save_config(self.config)
                print_system("系统提示词已更新")
            else:
                print_system(f"当前系统提示词: {self.config.get('system_prompt', '(无)')}")
        elif command == "/history":
            self._show_history()
        elif command == "/react":
            if args.strip():
                self._run_react(args.strip())
            else:
                print_system("用法: /react <问题>  （ReAct：推理与工具调用，需配置 API Key）")
        else:
            print_error(f"未知命令: {command}，输入 /help 查看帮助")

        return True

    def _show_help(self):
        render_stream(demo_stream("帮助"))

    def _run_react(self, question: str):
        """ReAct 模式：多步推理 + 工具调用，结果以 Markdown 面板展示。"""
        print_user_message(f"/react {question}")
        agent = ReActAgent("MyCLI", self.llm)
        answer = agent.run(question)
        self.messages.append({"role": "user", "content": f"[ReAct] {question}"})
        self.messages.append({"role": "assistant", "content": answer})
        render_stream(stream_text(answer))

    def _show_history(self):
        if len(self.messages) <= 1:
            print_system("暂无对话历史")
            return
        console.print()
        for msg in self.messages[1:]:  # 跳过 system
            role = "❯ 你" if msg["role"] == "user" else "🤖 助手"
            text = msg["content"][:80] + "..." if len(msg["content"]) > 80 else msg["content"]
            style = "cyan" if msg["role"] == "user" else "green"
            console.print(f"  {role}: {text}", style=style)

    def chat(self, user_input: str):
        """处理一轮对话"""
        self.messages.append({"role": "user", "content": user_input})
        print_user_message(user_input)

        if self.use_demo:
            stream = demo_stream(user_input)
        else:
            stream = self.llm.stream(self.messages)

        reply = render_stream(stream)
        self.messages.append({"role": "assistant", "content": reply})

    def run(self):
        print_welcome()

        if self.use_demo:
            print_system("演示模式（未检测到 API Key，设置 OPENAI_API_KEY 环境变量以连接 AI）")

        while True:
            try:
                user_input = self.session.prompt(
                    [("class:prompt", "  ❯ ")],
                ).strip()

                if not user_input:
                    continue

                if user_input.startswith("/"):
                    if not self.handle_command(user_input):
                        print_system("再见！👋")
                        break
                else:
                    stripped = user_input.strip()
                    if stripped.lower() == "react":
                        print_system("用法: react <问题> 或 /react <问题>")
                        continue
                    m = re.match(r"(?i)react\s+(.+)", stripped)
                    if m:
                        self._run_react(m.group(1).strip())
                    else:
                        self.chat(user_input)

            except KeyboardInterrupt:
                print_system("再见！👋")
                break
            except EOFError:
                break
        exit_fullscreen()
