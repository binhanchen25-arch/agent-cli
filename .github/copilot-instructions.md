# Copilot Instructions for MyCLI

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run the app
python main.py

# Run all tests
python -m unittest discover -s test -p "test_*.py"

# Run a single test file
python -m unittest test.test_cli_app

# Run a single test method
python -m unittest test.test_cli_app.ChatAppTests.test_exit_command_returns_false
```

## Architecture

MyCLI is a terminal AI assistant with two modes: **chat** (streaming LLM conversation) and **ReAct agent** (multi-step reasoning with tool calls via OpenAI Function Calling).

- **`main.py`** → entry point, creates and runs `ChatApp`
- **`core/config.py`** → config layering: env vars > `.env` > `~/.mycli/config.json` > defaults. All modules share a single `config` dict reference.
- **`core/llm.py`** → `OpenAICompatLLM` wraps the OpenAI SDK. Provides `invoke()` (non-streaming), `invoke_with_tools()` (Function Calling), and `stream()`. Falls back to mock/demo responses when no API key is set.
- **`core/reagent.py`** → `ReActAgent` runs Function Calling loops (up to `max_steps`). `ReActChatLLM` adapts the agent to the same `stream()`/`invoke()` interface `ChatApp` expects, so the app can swap between chat and agent mode transparently.
- **`cli/app.py`** → `ChatApp` owns the REPL, slash-command dispatch, conversation history, and LLM instance. Switching modes (`/react`, `/chat`) swaps `self.llm` between `OpenAICompatLLM` and `ReActChatLLM`.
- **`cli/renderer.py`** → all terminal output goes through a shared `console` (Rich). `render_stream()` uses `Rich.Live` for streaming Markdown panels.
- **`tools/`** → tool system for the agent:
  - `base.py` — `Tool` ABC, `ToolParameter` (Pydantic model), `@tool_action` decorator for expandable sub-tools, `UserRefusedError` exception
  - `registry.py` — `ToolRegistry` handles lookup, schema generation (`get_openai_tools_schema()`), and execution
  - `builtin.py` — built-in tools: `echo`, `now`, `windows_cmd`, `tree`, `glob`, `grep`, `view`. `default_tool_registry()` creates the standard set.

## Key Conventions

- **Language**: Code comments, docstrings, system prompts, and UI strings are in Chinese. Keep this consistent.
- **Tool pattern**: Every tool subclasses `Tool`, implements `get_parameters() -> List[ToolParameter]` and `run(parameters: dict) -> str`. Parameters use JSON Schema type strings (`"string"`, `"integer"`, `"array"`, etc.). Register new tools in `default_tool_registry()` inside `builtin.py`.
- **Expandable tools**: Set `expandable=True` and use `@tool_action` decorator on methods to auto-generate sub-tools with parameters inferred from type hints and docstrings.
- **User confirmation flow**: `WindowsCmdTool` requires CLI confirmation before execution. Users toggle this with `/allow`. When the user refuses, `UserRefusedError` is raised and the agent gracefully falls back to `_finish_on_refused()`.
- **LLM interface contract**: Any object used as `self.llm` in `ChatApp` must provide `stream(messages) -> Generator[str]` and `invoke(messages) -> str`. This is how `ReActChatLLM` adapts the agent into the chat pipeline.
- **Testing**: Tests use `unittest` with `unittest.mock`. `ChatApp` tests patch all external dependencies (config, prompt session, LLM) to run without I/O. Follow this pattern for new tests.
- **No type checker or linter configured** — CI only runs `unittest`.
