"""The agent loop: stream the model's reply, run any tool calls it asks for,
feed the results back, and repeat until it stops calling tools.

Also handles context compaction, project-memory injection, and the todo plan.
"""

from __future__ import annotations

import json
from typing import Callable, Optional

from .backends import Backend
from .config import (COMPACT_AT, CONTEXT_TOKENS, KEEP_RECENT, MAX_AGENT_STEPS,
                     SYSTEM_PROMPT, estimate_tokens)
from . import tools

Confirm = Callable[[str, str, str], bool]
OnToken = Callable[[str], None]
OnTurnEnd = Callable[[], None]
OnTool = Callable[[str, dict], None]
OnToolResult = Callable[[str, dict, str], None]
OnTodos = Callable[[list], None]
OnNotice = Callable[[str], None]
OnAsk = Callable[[str, list], str]
OnWaitStart = Callable[[], None]
OnWaitEnd = Callable[[], None]


class Agent:
    def __init__(self, backend: Backend, confirm: Confirm, on_token: OnToken,
                 on_turn_end: OnTurnEnd, on_tool: OnTool,
                 on_todos: Optional[OnTodos] = None,
                 on_notice: Optional[OnNotice] = None,
                 on_tool_result: Optional[OnToolResult] = None,
                 on_ask: Optional[OnAsk] = None,
                 on_wait_start: Optional[OnWaitStart] = None,
                 on_wait_end: Optional[OnWaitEnd] = None,
                 project_memory: str = "", settings=None, mcp=None,
                 depth: int = 0):
        self.backend = backend
        self.confirm = confirm
        self.on_token = on_token
        self.on_turn_end = on_turn_end
        self.on_tool = on_tool
        self.on_tool_result = on_tool_result or (lambda n, a, r: None)
        self.on_ask = on_ask or (lambda q, o: (o[0] if o else ""))
        self.on_todos = on_todos or (lambda t: None)
        self.on_notice = on_notice or (lambda s: None)
        self.on_wait_start = on_wait_start or (lambda: None)
        self.on_wait_end = on_wait_end or (lambda: None)
        self.project_memory = project_memory
        self.settings = settings
        self.mcp = mcp
        self.depth = depth
        self.todos: list[dict] = []
        self.messages: list[dict] = [self._system()]

    def reset(self) -> None:
        self.messages = [self._system()]
        self.todos = []

    def context_tokens(self) -> int:
        return estimate_tokens(self.messages)

    def conversation_tokens(self) -> int:
        """Tokens from the actual conversation, excluding the system prompt
        and project memory — so a fresh session reads 0."""
        body = [m for m in self.messages if m.get("role") != "system"]
        return estimate_tokens(body) if body else 0

    def load_messages(self, messages: list[dict]) -> None:
        """Adopt a restored transcript, refreshing the system prompt."""
        body = [m for m in messages if m.get("role") != "system"]
        self.messages = [self._system(), *body]

    def send(self, user_input: str) -> None:
        """Run one full turn: user message -> (model <-> tools)* -> final reply."""
        self.messages.append({"role": "user", "content": user_input})
        self._maybe_compact()

        for _ in range(MAX_AGENT_STEPS):
            content, tool_calls = self._stream_once()

            entry: dict = {"role": "assistant", "content": content}
            if tool_calls:
                entry["tool_calls"] = [
                    {"id": tc["id"], "type": "function",
                     "function": {"name": tc["name"], "arguments": tc["arguments"]}}
                    for tc in tool_calls
                ]
            self.messages.append(entry)

            if not tool_calls:
                return

            for tc in tool_calls:
                args = _parse_args(tc["arguments"])
                self.on_tool(tc["name"], args)
                result = self._run_tool(tc["name"], args)
                self.on_tool_result(tc["name"], args, result)
                self.messages.append({"role": "tool",
                                      "tool_call_id": tc["id"],
                                      "content": result})

        self.on_token("\n[stopped: hit the max step limit for this turn]")
        self.on_turn_end()

    def _system(self) -> dict:
        content = SYSTEM_PROMPT
        if self.project_memory:
            content += "\n\n" + self.project_memory
        return {"role": "system", "content": content}

    def _run_tool(self, name: str, args: dict) -> str:
        if name == "update_todos":
            self.todos = _normalize_todos(args.get("todos", []))
            self.on_todos(self.todos)
            done = sum(t["status"] == "completed" for t in self.todos)
            return f"OK: todos updated ({done}/{len(self.todos)} complete)"
        if name == "ask_user":
            choice = self.on_ask(args.get("question", ""),
                                 args.get("options", []) or [])
            return f"User chose: {choice}"
        if name == "spawn_agent":
            return self._spawn(args.get("task", ""))
        if self.mcp and self.mcp.handles(name):
            return self.mcp.call(name, args)

        if name == "run_command":
            result = tools.dispatch(name, args, self.confirm, on_output=self.on_token)
        else:
            result = tools.dispatch(name, args, self.confirm)
        return self._fire_hooks(name, args, result)

    def _fire_hooks(self, name: str, args: dict, result: str) -> str:
        if not self.settings or not result.startswith("OK"):
            return result
        from . import hooks
        event = {"write_file": "after_write", "edit_file": "after_edit",
                 "run_command": "after_command"}.get(name)
        if not event:
            return result
        note = hooks.run_hooks(self.settings, event,
                               path=args.get("path", ""),
                               command=args.get("command", ""))
        return f"{result}\n{note}" if note else result

    def _spawn(self, task: str) -> str:
        if self.depth >= 1:
            return "ERROR: sub-agents cannot spawn more sub-agents."
        if not task.strip():
            return "ERROR: spawn_agent needs a task."
        self.on_notice(f"sub-agent ▷ {task[:70]}")
        child = Agent(self.backend,
                      confirm=self.confirm,
                      on_token=lambda s: self.on_token(s),
                      on_turn_end=self.on_turn_end,
                      on_tool=lambda n, a: self.on_notice(f"  sub · {n}"),
                      on_notice=self.on_notice, on_ask=self.on_ask,
                      project_memory=self.project_memory,
                      settings=self.settings, mcp=self.mcp, depth=self.depth + 1)
        try:
            child.send(task)
        except Exception as e:
            return f"ERROR in sub-agent: {e}"
        report = next((m["content"] for m in reversed(child.messages)
                       if m["role"] == "assistant" and m.get("content")),
                      "(sub-agent produced no report)")
        return f"[sub-agent report]\n{report}"

    def _schemas(self) -> list[dict]:
        schemas = list(tools.TOOL_SCHEMAS)
        if self.depth >= 1:
            schemas = [s for s in schemas
                       if s["function"]["name"] != "spawn_agent"]
        if self.mcp:
            schemas += self.mcp.schemas()
        return schemas

    def _stream_once(self):
        """One streamed model call. Returns (content, tool_calls list)."""
        self.on_wait_start()
        waiting = True
        stream = self.backend.client.chat.completions.create(
            model=self.backend.model,
            messages=self.messages,
            tools=self._schemas(),
            temperature=0.2,
            stream=True,
        )

        content_parts: list[str] = []
        calls: dict[int, dict] = {}
        printed_any = False

        try:
            for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta

                if getattr(delta, "content", None):
                    self.on_token(delta.content)
                    content_parts.append(delta.content)
                    printed_any = True

                for tc in (getattr(delta, "tool_calls", None) or []):
                    if waiting:
                        self.on_wait_end(); waiting = False
                    slot = calls.setdefault(tc.index,
                                            {"id": "", "name": "", "arguments": ""})
                    if tc.id:
                        slot["id"] = tc.id
                    if tc.function:
                        if tc.function.name:
                            slot["name"] += tc.function.name
                        if tc.function.arguments:
                            slot["arguments"] += tc.function.arguments
        finally:
            if waiting:
                self.on_wait_end()

        if printed_any:
            self.on_turn_end()

        ordered = [calls[i] for i in sorted(calls)]
        for n, c in enumerate(ordered):
            if not c["id"]:
                c["id"] = f"call_{n}"
        return "".join(content_parts), ordered

    def compact(self, force: bool = False) -> bool:
        return self._maybe_compact(force=force)

    def _maybe_compact(self, force: bool = False) -> bool:
        budget = CONTEXT_TOKENS
        if not force and estimate_tokens(self.messages) < budget * COMPACT_AT:
            return False

        body = self.messages[1:]
        if len(body) <= KEEP_RECENT:
            return False

        split = max(0, len(body) - KEEP_RECENT)
        while split < len(body) and body[split]["role"] != "user":
            split += 1
        to_summarize, tail = body[:split], body[split:]
        if not to_summarize:
            return False

        self.on_notice("compacting earlier conversation…")
        summary = self._summarize(to_summarize)
        self.messages = [
            self._system(),
            {"role": "user",
             "content": "[Summary of earlier conversation]\n" + summary},
            {"role": "assistant", "content": "Got it — continuing from there."},
            *tail,
        ]
        return True

    def _summarize(self, msgs: list[dict]) -> str:
        transcript = _render(msgs)
        try:
            resp = self.backend.client.chat.completions.create(
                model=self.backend.model,
                messages=[
                    {"role": "system",
                     "content": "Summarize this coding-session transcript so work "
                                "can continue. Capture: the user's goals, decisions "
                                "made, files created/changed, and any open TODOs. "
                                "Be concise and factual."},
                    {"role": "user", "content": transcript[:12000]},
                ],
                temperature=0.1,
                stream=False,
            )
            return resp.choices[0].message.content or "(summary unavailable)"
        except Exception as e:
            return f"(summary failed: {e})"


_VALID_STATUS = {"pending", "in_progress", "completed"}


def _normalize_todos(raw) -> list[dict]:
    """Coerce whatever the model sent into [{content, status}], since smaller
    models often return bare strings, a JSON-encoded string, or a bad status."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            raw = [raw]
    if isinstance(raw, dict):
        raw = raw.get("todos", [raw]) if "todos" in raw else [raw]
    out = []
    for item in raw or []:
        if isinstance(item, str):
            out.append({"content": item, "status": "pending"})
        elif isinstance(item, dict):
            content = (item.get("content") or item.get("task")
                       or item.get("text") or "").strip()
            if not content:
                continue
            status = str(item.get("status", "pending")).lower()
            if status not in _VALID_STATUS:
                status = "pending"
            out.append({"content": content, "status": status})
    return out


def _render(msgs: list[dict]) -> str:
    out = []
    for m in msgs:
        role = m.get("role")
        if role == "tool":
            out.append(f"[tool result] {(m.get('content') or '')[:400]}")
        elif role == "assistant":
            if m.get("content"):
                out.append(f"[assistant] {m['content']}")
            for tc in m.get("tool_calls", []) or []:
                fn = tc.get("function", {})
                out.append(f"[assistant called {fn.get('name')}] {fn.get('arguments','')[:200]}")
        elif role == "user":
            out.append(f"[user] {m.get('content','')}")
    return "\n".join(out)


def _parse_args(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
