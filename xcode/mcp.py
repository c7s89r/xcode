"""Minimal MCP (Model Context Protocol) client.

Launches MCP servers over stdio (newline-delimited JSON-RPC 2.0), lists their
tools, and lets the agent call them. Servers are declared in
.xcode/settings.json:

  "mcpServers": {
    "fs": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "."]}
  }

Each server tool is exposed to the model as  mcp__<server>__<tool>.
"""

from __future__ import annotations

import json
import queue
import subprocess
import threading
from typing import Optional

PROTOCOL = "2024-11-05"


class McpClient:
    def __init__(self, name: str, command: str, args: list[str],
                 env: Optional[dict] = None):
        self.name = name
        self.tools: list[dict] = []
        self._id = 0
        self._inbox: "queue.Queue[dict]" = queue.Queue()
        self.proc = subprocess.Popen(
            [command, *args], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, bufsize=1, env=_merged_env(env))
        threading.Thread(target=self._reader, daemon=True).start()

    def initialize(self) -> None:
        self._request("initialize", {
            "protocolVersion": PROTOCOL,
            "capabilities": {},
            "clientInfo": {"name": "xcode", "version": "0.1"},
        })
        self._notify("notifications/initialized", {})
        res = self._request("tools/list", {})
        self.tools = (res or {}).get("tools", [])

    def call(self, tool: str, arguments: dict) -> str:
        res = self._request("tools/call", {"name": tool, "arguments": arguments})
        if res is None:
            return f"ERROR: no response from MCP server '{self.name}'"
        parts = []
        for block in res.get("content", []):
            if block.get("type") == "text":
                parts.append(block.get("text", ""))
            else:
                parts.append(json.dumps(block))
        out = "\n".join(parts) if parts else json.dumps(res)
        return ("ERROR: " + out) if res.get("isError") else out

    def close(self) -> None:
        try:
            self.proc.terminate()
        except Exception:
            pass

    def _reader(self) -> None:
        for line in self.proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                self._inbox.put(json.loads(line))
            except json.JSONDecodeError:
                continue

    def _send(self, obj: dict) -> None:
        self.proc.stdin.write(json.dumps(obj) + "\n")
        self.proc.stdin.flush()

    def _notify(self, method: str, params: dict) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def _request(self, method: str, params: dict, timeout: float = 30) -> Optional[dict]:
        self._id += 1
        rid = self._id
        self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        while True:
            try:
                msg = self._inbox.get(timeout=timeout)
            except queue.Empty:
                return None
            if msg.get("id") == rid:
                if "error" in msg:
                    return {"isError": True,
                            "content": [{"type": "text",
                                         "text": json.dumps(msg["error"])}]}
                return msg.get("result", {})


class McpManager:
    """Owns all connected servers and exposes their tools to the agent."""

    def __init__(self):
        self.clients: dict[str, McpClient] = {}

    def connect_all(self, servers: dict, on_status=lambda s: None) -> None:
        for name, cfg in (servers or {}).items():
            try:
                c = McpClient(name, cfg["command"], cfg.get("args", []),
                              cfg.get("env"))
                c.initialize()
                self.clients[name] = c
                on_status(f"MCP '{name}': {len(c.tools)} tools")
            except Exception as e:
                on_status(f"MCP '{name}' failed: {e}")

    def schemas(self) -> list[dict]:
        """OpenAI-format tool schemas for every MCP tool, namespaced."""
        out = []
        for name, client in self.clients.items():
            for t in client.tools:
                out.append({"type": "function", "function": {
                    "name": f"mcp__{name}__{t['name']}",
                    "description": f"[{name}] {t.get('description', '')}",
                    "parameters": t.get("inputSchema",
                                        {"type": "object", "properties": {}}),
                }})
        return out

    def handles(self, tool_name: str) -> bool:
        return tool_name.startswith("mcp__")

    def call(self, tool_name: str, args: dict) -> str:
        try:
            _, server, tool = tool_name.split("__", 2)
        except ValueError:
            return f"ERROR: malformed MCP tool name '{tool_name}'"
        client = self.clients.get(server)
        if not client:
            return f"ERROR: no MCP server '{server}'"
        return client.call(tool, args)

    def close(self) -> None:
        for c in self.clients.values():
            c.close()


def _merged_env(env: Optional[dict]) -> Optional[dict]:
    if not env:
        return None
    import os
    merged = dict(os.environ)
    merged.update({k: str(v) for k, v in env.items()})
    return merged
