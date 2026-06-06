MyCLI（终端原生 AI 助手 / Agent 框架） (开源项目目前有 N 个 star，N 个 fork)
github 地址：https://github.com/<your-username>/mycli
基于 OpenAI 兼容原生 API 封装的终端 AI 助手与 Agent 框架，支持流式聊天与 ReAct 智能体双模式无缝切换
• 双模架构：基于原生 OpenAI 兼容 API 实现「流式聊天 / ReAct 智能体」两种模式，通过 ReActChatLLM 适配器把 Agent 统一到 stream() / invoke() 接口契约，使 ChatApp 在聊天与 Agent 模式之间透明切换。
• ReAct 智能体：基于 OpenAI Function Calling 实现多步推理与并行工具调用循环（最大步数可配），支持工具事件实时流式 token 透传、Ctrl+C 中断与连接清理、用户拒绝后优雅收尾（UserRefusedError + _finish_on_refused）。
• 分片增量构建 Prompt + KV Cache 复用：messages 采用「稳定前缀（system + history + 首轮 user question）+ 逐步追加（assistant tool_calls / tool result）」的分片构建策略，每一步 Function Calling 循环仅向尾部 append 新的 tool_calls 与 tool 结果消息、不重建已有前缀，从而使服务端推理引擎能命中 Prefix KV Cache、跳过已计算 token 的 attention 计算，显著降低多步 Agent 场景下的 TTFT 与 token 成本。
• 工具系统：设计 Tool 抽象基类 + ToolParameter（Pydantic）+ @tool_action 子工具装饰器，ToolRegistry 自动根据类型注解与 docstring 生成 OpenAI Function Calling JSON Schema 并分发执行，内置 echo、now、tree、glob、grep、view、write_file、edit_file、fetch_url、python_repl、file_ops、create_docx、web_search 等 10+ 工具。
• 工具确认机制：实现「模型自主 confirm 参数 + 全局默认开关 + 终端 yes_no_dialog 弹窗」三层确认体系，TTY/非 TTY 自动降级，针对 write_file、python_repl、windows_cmd 等高风险操作提供可信执行隔离。
• 中间件 / Hook 系统：实现 before_step 用户钩子的动态加载器（importlib.util + mtime 热重载），支持上下文裁剪、提示词注入、调用日志等扩展能力，无需修改源码即可定制 Agent 行为，异常自动隔离不影响主流程。
• Agent SDK 入口：参考 Claude Code「一份源码、多张脸」架构拆分 entrypoints/，对外暴露 query()、QueryOptions、Tool、ToolRegistry 等稳定 Public Surface，支持 mycli sdk-schema 一键 dump JSON Schema，可作为库被其他 Python 程序集成调用。
• 启动性能优化：CLI 入口采用「门房模式」分快速/慢速路径，--version、--help、--config-path 等命令在加载 OpenAI / Rich / prompt_toolkit 等重型依赖前即时返回，节省数百毫秒启动开销。
• 上下文管理：基于 tiktoken 实现 messages token 精确计数（无依赖时按字节/字符自适应估算回退），内置 GPT-4o、Claude、DeepSeek、Gemini、Qwen 等 20+ 主流模型的上下文窗口常量表，实时展示上下文占用率。
• 配置体系：实现 .env + <cwd>/.mycli/config.json 两层配置加载，环境变量优先级与 load_dotenv 兼容，支持不同项目独立配置、历史与钩子隔离。
• 终端 UX：基于 Rich + prompt_toolkit 实现流式 Markdown 渲染（Rich.Live）、Spinner 状态提示、斜杠命令自动补全、备用屏幕缓冲区（与 vim/less 一致的退出恢复）；无 API Key 时自动进入演示模式便于试用。
