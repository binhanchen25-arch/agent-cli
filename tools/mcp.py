"""MCP (Model Context Protocol) 客户端 + 工具适配器（stdio JSON-RPC 版）。

最小可用实现：
- 通过 `subprocess.Popen` 启动 MCP server，stdin/stdout 走 JSON-RPC 2.0 ndjson。
- 支持 `initialize` 握手 → `tools/list` 拉取工具 → `tools/call` 执行调用。
- 每个远端工具包装为 `McpTool`，与本地 Tool 一样接入 ToolRegistry。

设计取舍：
- 不依赖外部 `mcp` SDK，关键路径自实现，方便嵌入轻量 CLI。
- 默认所有 MCP 工具 `always_visible=False`：必须通过 `tool_search` 发现，避免一个
  server 几十个 tool 撑爆 LLM 上下文。
- 失败处理：server 启动失败 / list 失败 → registry 记录错误，不影响 CLI 其他能力。

注意事项：
- MCP server 必须使用 stdio transport（绝大多数官方 server 默认即此）。
- 本实现假定 server 输出标准 ndjson（一条消息一行）；某些 server 可能用 LSP
  Content-Length 帧，需要在此扩展 _read_message()。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from tools.base import Tool, ToolParameter


# ── 数据结构 ─────────────────────────────────────────────────────────────────


@dataclass
class McpServerConfig:
    """MCP 服务器启动配置。"""

    name: str
    command: str
    args: List[str] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)
    # 启动后等待 initialize 响应的秒数。
    timeout: float = 15.0


@dataclass
class McpToolDef:
    """从 server 的 `tools/list` 拿到的远端工具描述。"""

    name: str
    description: str
    input_schema: Dict[str, Any]


# ── JSON-RPC 客户端 ───────────────────────────────────────────────────────────


class McpClient:
    """与单个 MCP server 通信的最小客户端（stdio + JSON-RPC 2.0 ndjson）。"""

    PROTOCOL_VERSION = "2025-06-18"

    def __init__(self, config: McpServerConfig) -> None:
        self.config = config
        self._proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()  # 串行化 send/recv
        self._next_id = 1
        self._stderr_thread: Optional[threading.Thread] = None

    # ── 生命周期 ──

    def start(self) -> None:
        """启动子进程并完成 initialize 握手。"""
        env = os.environ.copy()
        env.update(self.config.env or {})

        self._proc = subprocess.Popen(
            [self.config.command, *self.config.args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            text=True,
            bufsize=1,  # 行缓冲
        )

        # 把 stderr 异步排空，避免阻塞 server。
        self._stderr_thread = threading.Thread(
            target=self._drain_stderr, daemon=True
        )
        self._stderr_thread.start()

        # initialize 握手
        try:
            self._send_request(
                "initialize",
                {
                    "protocolVersion": self.PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "mycli", "version": "0.1"},
                },
            )
        except Exception:
            self.close()
            raise

        # 通知 server 初始化完成
        self._send_notification("notifications/initialized", {})

    def close(self) -> None:
        if self._proc is None:
            return
        try:
            if self._proc.poll() is None:
                self._proc.terminate()
                try:
                    self._proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self._proc.kill()
        finally:
            self._proc = None

    def _drain_stderr(self) -> None:
        proc = self._proc
        if proc is None or proc.stderr is None:
            return
        try:
            for _ in iter(proc.stderr.readline, ""):
                pass  # 静默丢弃；如需调试可改成 sys.stderr.write
        except Exception:
            pass

    # ── 公开 API ──

    def list_tools(self) -> List[McpToolDef]:
        resp = self._send_request("tools/list", {})
        result = resp.get("result", {}) or {}
        out: List[McpToolDef] = []
        for t in result.get("tools", []) or []:
            out.append(McpToolDef(
                name=str(t.get("name", "")),
                description=str(t.get("description", "")),
                input_schema=t.get("inputSchema") or {},
            ))
        return [t for t in out if t.name]

    def call_tool(self, name: str, arguments: Dict[str, Any]) -> str:
        resp = self._send_request(
            "tools/call",
            {"name": name, "arguments": arguments},
        )
        result = resp.get("result", {}) or {}

        # MCP 标准：result.content 是数组，每项 {type: "text", text: "..."}
        content = result.get("content") or []
        parts: List[str] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text":
                parts.append(str(item.get("text", "")))
            else:
                parts.append(json.dumps(item, ensure_ascii=False))

        text = "\n".join(parts).strip()
        if result.get("isError"):
            return f"[MCP 错误] {text or '远端工具返回 isError=true'}"
        return text or json.dumps(result, ensure_ascii=False)

    # ── 底层 JSON-RPC ──

    def _send_request(self, method: str, params: Optional[dict] = None) -> dict:
        if self._proc is None or self._proc.stdin is None or self._proc.stdout is None:
            raise RuntimeError("MCP client 未启动")

        with self._lock:
            rid = self._next_id
            self._next_id += 1

            msg = {
                "jsonrpc": "2.0",
                "id": rid,
                "method": method,
                "params": params or {},
            }
            line = json.dumps(msg, ensure_ascii=False) + "\n"
            self._proc.stdin.write(line)
            self._proc.stdin.flush()

            # 读响应（跳过不带 id 的 notification）
            while True:
                raw = self._proc.stdout.readline()
                if not raw:
                    raise RuntimeError(
                        f"MCP server '{self.config.name}' 在等待 {method} 响应时关闭了 stdout"
                    )
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if data.get("id") != rid:
                    continue
                if "error" in data:
                    err = data["error"]
                    raise RuntimeError(
                        f"MCP server '{self.config.name}' {method} 失败: "
                        f"{err.get('code')} {err.get('message')}"
                    )
                return data

    def _send_notification(self, method: str, params: Optional[dict] = None) -> None:
        if self._proc is None or self._proc.stdin is None:
            return
        msg = {"jsonrpc": "2.0", "method": method, "params": params or {}}
        line = json.dumps(msg, ensure_ascii=False) + "\n"
        try:
            self._proc.stdin.write(line)
            self._proc.stdin.flush()
        except Exception:
            pass


# ── Tool 适配器 ──────────────────────────────────────────────────────────────


def _schema_to_parameters(schema: Dict[str, Any]) -> List[ToolParameter]:
    """把 MCP inputSchema (JSON Schema) 翻译成 ToolParameter 列表。"""
    props = (schema or {}).get("properties", {}) or {}
    required = set((schema or {}).get("required", []) or [])
    out: List[ToolParameter] = []
    for name, prop in props.items():
        if not isinstance(prop, dict):
            continue
        ptype = prop.get("type")
        # JSON Schema 的 type 可能是 list（联合）；取第一项简化处理。
        if isinstance(ptype, list):
            ptype = next((t for t in ptype if t != "null"), "string")
        if ptype not in ("string", "integer", "number", "boolean", "array", "object"):
            ptype = "string"
        out.append(ToolParameter(
            name=str(name),
            type=str(ptype),
            description=str(prop.get("description") or f"参数 {name}"),
            required=name in required,
            default=prop.get("default"),
        ))
    return out


class McpTool(Tool):
    """把一个远端 MCP tool 包装成本地 `Tool`。"""

    # 远端工具行为未知 → fail-closed：默认非只读、不并发、不破坏。
    # 想批量改行为可在 register 时通过子类化覆盖。
    always_visible = False  # 默认靠 tool_search 发现，避免污染 schema

    def __init__(
        self,
        client: McpClient,
        tool_def: McpToolDef,
        name_prefix: str = "",
    ) -> None:
        local_name = f"{name_prefix}{tool_def.name}" if name_prefix else tool_def.name
        super().__init__(
            name=local_name,
            description=tool_def.description or f"MCP 工具 {tool_def.name}",
            expandable=False,
        )
        self.search_hint = f"MCP/{client.config.name}: {tool_def.description[:40]}"
        self._client = client
        self._remote_name = tool_def.name
        self._parameters = _schema_to_parameters(tool_def.input_schema)

    def get_parameters(self) -> List[ToolParameter]:
        return self._parameters

    def is_destructive(self, parameters=None) -> bool:
        # 不知道远端行为 → 走兜底确认，安全为先。
        return True

    def run(self, parameters: Dict[str, Any]) -> str:
        try:
            return self._client.call_tool(self._remote_name, parameters)
        except Exception as e:
            return f"MCP 调用失败: {type(e).__name__}: {e}"


# ── Registry 集成入口 ────────────────────────────────────────────────────────


def register_mcp_server(
    registry,
    config: McpServerConfig,
    name_prefix: str = "",
    always_visible: bool = False,
) -> List[str]:
    """启动 MCP server 并把它暴露的工具注册到 registry。

    Args:
        registry: ToolRegistry 实例。
        config: MCP server 启动配置。
        name_prefix: 远端工具名前缀（如 "github_"），防止与本地工具同名冲突。
        always_visible: 是否让 LLM 默认看到这些工具的 schema。
            False（默认）= 通过 `tool_search` 发现后再暴露，节省上下文。

    Returns:
        成功注册的本地工具名列表。失败时返回空列表，并在 registry 中记录错误。
    """
    client = McpClient(config)
    try:
        client.start()
        tool_defs = client.list_tools()
    except Exception as e:
        sys.stderr.write(
            f"[mcp] server '{config.name}' 启动/list 失败：{type(e).__name__}: {e}\n"
        )
        client.close()
        return []

    # CLI 退出时关闭子进程
    registry.add_closer(client.close)

    registered: List[str] = []
    for tdef in tool_defs:
        local_name = f"{name_prefix}{tdef.name}" if name_prefix else tdef.name

        # 用闭包打包成 factory，支持懒加载（虽然首次 list 已经实例化，
        # 这里直接走 register() 即可——保持代码简单）
        tool = McpTool(client, tdef, name_prefix=name_prefix)
        if always_visible:
            tool.always_visible = True
        registry.register(tool)
        registered.append(local_name)

    return registered
