from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.styles import Style
from datetime import datetime
import uuid

from cli.completer import CliCompleter
from cli.context_usage import calculate_context_usage
from cli.renderer import (
    print_welcome, print_user_message, render_stream,
    print_system, print_error, print_config, clear_screen, console,
    exit_fullscreen,
)

from core.config import load_config, save_config, ensure_dirs, HISTORY_FILE
from core.llm import OpenAICompatLLM, demo_stream
from core.reagent import ReActAgent, ReActChatLLM
from memory import (
    build_session_memory_state,
    reset_memory_write_marker,
    schedule_session_memory_extract,
)
from memory.auto_writer import schedule_auto_memory_write
from runtime_log import get_log_file_path, is_runtime_log_enabled, log_event
from tools.builtin import default_tool_registry, set_allow_all_windows_cmd

prompt_style = Style.from_dict({
    "prompt": "ansicyan bold",
})


class ChatApp:
    def __init__(self):
        ensure_dirs()
        self.config = load_config()
        self.base_llm = OpenAICompatLLM(self.config)
        self.llm = self.base_llm
        self.messages = []  # 对话历史
        self.use_demo = not self.config.get("api_key")
        self.cli_session_id = f"{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"
        self.session_memory_state = build_session_memory_state(self.cli_session_id)

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

    def _log_event(self, event: str, **payload):
        log_event(self.config, event, **payload)

    def handle_command(self, cmd: str) -> bool:
        """处理斜杠命令，返回 True 表示继续，False 表示退出"""
        parts = cmd.strip().split(maxsplit=1)
        command = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        self._log_event("command_received", command=command, args=args)

        if command == "/exit":
            self._log_event("command_exit")
            return False
        elif command == "/help":
            self._show_help()
        elif command == "/clear":
            self.messages = self.messages[:1]  # 保留 system prompt
            clear_screen()
            print_system("对话已清空")
        elif command == "/config":
            print_config(self.config)
        elif command == "/allow":
            allow_arg = args.strip().lower()
            if not allow_arg or allow_arg == "all":
                set_allow_all_windows_cmd(True)
                print_system("已开启 allow：所有工具默认直接执行（不再弹出 Yes/No 确认）。")
            elif allow_arg in ("off", "none", "reset"):
                set_allow_all_windows_cmd(False)
                print_system("已关闭 allow：所有工具默认执行前会弹出 Yes/No 确认。")
            else:
                print_system("用法: /allow  （可选: /allow all, /allow off）")
        elif command == "/log":
            log_arg = args.strip().lower()
            if log_arg in ("on", "enable", "start"):
                self.config["runtime_log_enabled"] = True
                save_config(self.config)
                print_system(f"已开启运行日志：{get_log_file_path(self.config)}")
                self._log_event("runtime_log_enabled", by_command="/log on")
            elif log_arg in ("off", "disable", "stop"):
                self._log_event("runtime_log_disabled", by_command="/log off")
                self.config["runtime_log_enabled"] = False
                save_config(self.config)
                print_system("已关闭运行日志")
            elif log_arg in ("status", ""):
                enabled = is_runtime_log_enabled(self.config)
                status = "开启" if enabled else "关闭"
                print_system(f"运行日志状态：{status}；文件：{get_log_file_path(self.config)}")
            else:
                print_system("用法: /log on | /log off | /log status")
        elif command in ("/chat", "/normal"):
            self.llm = self.base_llm
            print_system("已切换到普通聊天模式（LLM 直接对话）")
        elif command == "/model":
            if args:
                self.config["model"] = args
                save_config(self.config)
                print_system(f"模型已切换为: {args}")
            else:
                print_system(f"当前模型: {self.config['model']}")
        elif command == "/apikey":
            if args:
                self.config["api_key"] = args
                save_config(self.config)
                self.use_demo = False
                print_system("API Key 已更新")
            else:
                key = self.config.get("api_key", "")
                if key:
                    masked = key[:8] + "..." + key[-4:] if len(key) > 12 else "***"
                    print_system(f"当前 API Key: {masked}")
                else:
                    print_system("API Key 未设置。用法: /apikey <your-key>")
        elif command == "/base_url":
            if args:
                self.config["base_url"] = args
                save_config(self.config)
                print_system(f"Base URL 已更新为: {args}")
            else:
                print_system(f"当前 Base URL: {self.config.get('base_url', '(未设置)')}")
        elif command == "/temperature":
            if args:
                try:
                    val = float(args)
                    if not (0 <= val <= 2):
                        print_error("temperature 应在 0 到 2 之间")
                    else:
                        self.config["temperature"] = val
                        save_config(self.config)
                        print_system(f"temperature 已设置为: {val}")
                except ValueError:
                    print_error("temperature 必须是数字，如 /temperature 0.8")
            else:
                print_system(f"当前 temperature: {self.config.get('temperature', 0.8)}")
        elif command == "/max_tokens":
            if args:
                try:
                    val = int(args)
                    if val <= 0:
                        print_error("max_tokens 必须为正整数")
                    else:
                        self.config["max_tokens"] = val
                        save_config(self.config)
                        print_system(f"max_tokens 已设置为: {val}")
                except ValueError:
                    print_error("max_tokens 必须是整数，如 /max_tokens 4096")
            else:
                print_system(f"当前 max_tokens: {self.config.get('max_tokens', 2048)}")
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
        elif command == "/context":
            self._render_context_usage()
        elif command == "/react":
            # /react：把当前 llm 切换成 ReAct agent（包装成与 ChatApp 兼容的 stream/invoke 接口）
            # 默认带 with_agents=True，允许主 Agent 通过 `agent` 工具派遣子 Agent。
            registry = default_tool_registry(
                with_agents=True,
                base_llm=self.base_llm,
                config=self.config,
            )
            self.llm = ReActChatLLM(
                ReActAgent("MyCLI", self.base_llm, tool_registry=registry)
            )
            if args.strip():
                self._run_react(args.strip())
            else:
                print_system("已切换到 ReAct 模式（后续输入将走 ReActAgent；用 /chat 切回普通聊天）")
        else:
            print_error(f"未知命令: {command}，输入 /help 查看帮助")
            self._log_event("command_unknown", command=command)

        return True

    def _show_help(self):
        render_stream(demo_stream("帮助"))

    def _render_context_usage(self):
        """在 CLI 中渲染当前消息 token 与上下文占用。"""
        stats = calculate_context_usage(
            messages=self.messages,
            model=self.config.get("model", "gpt-4o-mini"),
        )
        print_system(
            "当前内容 token 占用: "
            f"{int(stats['token_count'])}/{int(stats['context_window'])} tokens "
            f"({stats['context_percent']}%), "
            f"剩余 {int(stats['remaining_tokens'])} tokens"
        )
        return stats

    def _run_react(self, question: str):
        """ReAct 模式：多步推理 + 工具调用，结果以 Markdown 面板展示。"""
        reset_memory_write_marker()
        print_user_message(f"/react {question}")
        registry = default_tool_registry(
            with_agents=True,
            base_llm=self.base_llm,
            config=self.config,
        )
        agent = ReActAgent("MyCLI", self.base_llm, tool_registry=registry)
        stream = agent.run_stream(question, history=self.messages)
        answer = render_stream(stream)
        self.messages.append({"role": "user", "content": f"[ReAct] {question}"})
        self.messages.append({"role": "assistant", "content": answer})
        schedule_auto_memory_write(
            llm=self.base_llm,
            user_text=question,
            assistant_text=answer,
            memory_type="auto",
        )
        stats = self._render_context_usage()
        schedule_session_memory_extract(
            llm=self.base_llm,
            messages=self.messages,
            token_count=int(stats.get("token_count", 0)),
            turn_count=len(self.messages),
            state=self.session_memory_state,
        )

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
        reset_memory_write_marker()
        self.messages.append({"role": "user", "content": user_input})
        self._log_event("chat_started", input_preview=user_input[:120], use_demo=self.use_demo)
        # print_user_message(user_input)

        if self.use_demo:
            stream = demo_stream(user_input)
        else:
            stream = self.llm.stream(self.messages)

        reply = render_stream(stream)
        self.messages.append({"role": "assistant", "content": reply})
        schedule_auto_memory_write(
            llm=self.base_llm,
            user_text=user_input,
            assistant_text=reply,
            memory_type="auto",
        )
        self._log_event("chat_finished", reply_preview=reply[:120], total_messages=len(self.messages))
        stats = self._render_context_usage()
        schedule_session_memory_extract(
            llm=self.base_llm,
            messages=self.messages,
            token_count=int(stats.get("token_count", 0)),
            turn_count=len(self.messages),
            state=self.session_memory_state,
        )

    def run(self):
        print_welcome(self.cli_session_id)

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
                        print_system("请使用 /react 进入 ReAct 模式")
                        continue
                    self.chat(user_input)

            except KeyboardInterrupt:
                # 提示用 /exit 退出（流式中的 Ctrl+C 已由 render_stream 处理）
                print_system("按 Ctrl+C 已取消；输入 /exit 退出。")
                continue
            except EOFError:
                break
        exit_fullscreen()
