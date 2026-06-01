"""The tools the agent can call, their JSON schemas, and a dispatcher.

Each tool returns a string (what the model sees as the result). Tools that
mutate the system (write_file, edit_file, run_command) go through a confirm()
callback: confirm(kind, target, detail) -> bool, where the CLI may consult
persistent permission rules and/or ask the user.
"""

from __future__ import annotations

import difflib
import html
import re
import subprocess
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, unquote, urlparse

import httpx

Confirm = Callable[[str, str, str], bool]

MAX_OUTPUT = 20_000

RENDER: dict = {}
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv",
             ".xcode", "dist", "build", ".mypy_cache", ".pytest_cache"}

_BG: list = []


def background_count() -> int:
    """How many background shells are still running (finished ones pruned)."""
    _BG[:] = [p for p in _BG if p.poll() is None]
    return len(_BG)


def _clip(text: str) -> str:
    if len(text) > MAX_OUTPUT:
        return text[:MAX_OUTPUT] + f"\n... [clipped {len(text) - MAX_OUTPUT} chars]"
    return text


def _skipped(p: Path) -> bool:
    return any(part in SKIP_DIRS for part in p.parts)


def _diff(old: str, new: str, path: str) -> str:
    """A compact unified diff for confirmation previews."""
    lines = list(difflib.unified_diff(
        old.splitlines(), new.splitlines(),
        fromfile=path, tofile=path, lineterm="", n=2))
    if not lines:
        return "(no textual changes)"
    if len(lines) > 80:
        lines = lines[:80] + [f"... [{len(lines) - 80} more diff lines]"]
    return "\n".join(lines)


def read_file(path: str) -> str:
    p = Path(path)
    if not p.exists():
        return f"ERROR: no such file: {path}"
    if p.is_dir():
        return f"ERROR: {path} is a directory (use list_dir)"
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
        numbered = "\n".join(f"{i:>5}  {ln}"
                             for i, ln in enumerate(text.splitlines(), 1))
        return _clip(numbered)
    except Exception as e:
        return f"ERROR reading {path}: {e}"


def write_file(path: str, content: str, confirm: Confirm) -> str:
    p = Path(path)
    old = p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""
    diff = _diff(old, content, path)
    RENDER["diff"] = diff
    detail = f"{'Overwrite' if p.exists() else 'Create'} {path}\n\n{diff}"
    if not confirm("write_file", path, detail):
        return "DENIED: user declined the write."
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"OK: wrote {len(content)} chars to {path}"
    except Exception as e:
        return f"ERROR writing {path}: {e}"


def edit_file(path: str, old_string: str, new_string: str, confirm: Confirm) -> str:
    p = Path(path)
    if not p.exists():
        return f"ERROR: no such file: {path}"
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return f"ERROR reading {path}: {e}"

    count = text.count(old_string)
    if count == 0:
        return ("ERROR: old_string not found. It must match the file exactly "
                "(including whitespace). Read the file first.")
    if count > 1:
        return (f"ERROR: old_string appears {count} times; add surrounding "
                "context so it matches exactly once.")

    new_text = text.replace(old_string, new_string, 1)
    diff = _diff(text, new_text, path)
    RENDER["diff"] = diff
    detail = f"Edit {path}\n\n{diff}"
    if not confirm("edit_file", path, detail):
        return "DENIED: user declined the edit."
    try:
        p.write_text(new_text, encoding="utf-8")
        return f"OK: edited {path}"
    except Exception as e:
        return f"ERROR writing {path}: {e}"


def list_dir(path: str = ".") -> str:
    p = Path(path)
    if not p.exists():
        return f"ERROR: no such path: {path}"
    if p.is_file():
        return f"{path} (file, {p.stat().st_size} bytes)"
    try:
        entries = sorted(p.iterdir(), key=lambda e: (e.is_file(), e.name.lower()))
        lines = [f"{'DIR ' if e.is_dir() else 'FILE'}  {e.name}" for e in entries]
        return "\n".join(lines) or "(empty directory)"
    except Exception as e:
        return f"ERROR listing {path}: {e}"


def glob_files(pattern: str, path: str = ".") -> str:
    base = Path(path)
    if not base.exists():
        return f"ERROR: no such path: {path}"
    try:
        matches = [str(m) for m in sorted(base.glob(pattern))
                   if m.is_file() and not _skipped(m)]
    except Exception as e:
        return f"ERROR in glob '{pattern}': {e}"
    if not matches:
        return f"(no files match {pattern})"
    extra = ""
    if len(matches) > 200:
        extra = f"\n... [{len(matches) - 200} more]"
        matches = matches[:200]
    return "\n".join(matches) + extra


def grep(pattern: str, path: str = ".", glob: str = "**/*") -> str:
    try:
        rx = re.compile(pattern)
    except re.error as e:
        return f"ERROR: bad regex: {e}"
    base = Path(path)
    if not base.exists():
        return f"ERROR: no such path: {path}"

    hits: list[str] = []
    for f in base.glob(glob):
        if not f.is_file() or _skipped(f):
            continue
        try:
            for i, line in enumerate(f.read_text(encoding="utf-8",
                                                 errors="ignore").splitlines(), 1):
                if rx.search(line):
                    hits.append(f"{f}:{i}: {line.strip()[:200]}")
                    if len(hits) >= 200:
                        return "\n".join(hits) + "\n... [stopped at 200 matches]"
        except Exception:
            continue
    return "\n".join(hits) if hits else f"(no matches for /{pattern}/)"


def run_command(command: str, confirm: Confirm, background: bool = False, 
                on_output: Callable[[str], None] | None = None) -> str:
    """Run a shell command with real-time streaming output.
    
    Args:
        command: Shell command to execute
        confirm: Permission callback
        background: Run detached without waiting
        on_output: Optional callback for streaming output line-by-line
    """
    if not confirm("run_command", command, command):
        return "DENIED: user declined the command."
    
    if background:
        try:
            proc = subprocess.Popen(command, shell=True,
                                    stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL)
            _BG.append(proc)
            return (f"OK: started in background (pid {proc.pid}); "
                    f"{background_count()} background shell(s) running.")
        except Exception as e:
            return f"ERROR starting background command: {e}"
    
    if on_output:
        try:
            proc = subprocess.Popen(
                command, 
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=0,
                universal_newlines=True
            )
            
            output_lines = []
            
            while True:
                char = proc.stdout.read(1)
                if not char:
                    if proc.poll() is not None:
                        break
                    continue
                
                on_output(char)
                
                if char == '\n':
                    output_lines.append('')
                elif output_lines or char.strip():
                    if not output_lines:
                        output_lines.append('')
                    output_lines[-1] = output_lines[-1] + char
            
            proc.wait(timeout=120)
            
            body = '\n'.join(output_lines).strip()
            body += f"\n[exit {proc.returncode}]"
            
            return _clip(body)
            
        except subprocess.TimeoutExpired:
            proc.kill()
            return "ERROR: command timed out after 120s"
        except Exception as e:
            return f"ERROR running command: {e}"
    
    try:
        proc = subprocess.run(command, shell=True, capture_output=True,
                              text=True, timeout=120)
        body = proc.stdout or ""
        if proc.stderr:
            body += "\n[stderr]\n" + proc.stderr
        body += f"\n[exit {proc.returncode}]"
        return _clip(body.strip())
    except subprocess.TimeoutExpired:
        return "ERROR: command timed out after 120s"
    except Exception as e:
        return f"ERROR running command: {e}"


def _trim(s: str, n: int = 300) -> str:
    s = s.replace("\n", "\\n")
    return s if len(s) <= n else s[:n] + "…"


_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"[ \t]*\n[ \t\n]*")


def _html_to_text(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", raw)
    raw = re.sub(r"(?i)<br\s*/?>", "\n", raw)
    raw = re.sub(r"(?i)</(p|div|li|h[1-6]|tr)>", "\n", raw)
    text = html.unescape(_TAG.sub("", raw))
    return _WS.sub("\n", text).strip()


def web_fetch(url: str) -> str:
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        r = httpx.get(url, timeout=15, follow_redirects=True,
                      headers={"User-Agent": "Mozilla/5.0 (xcode)"})
        r.raise_for_status()
    except Exception as e:
        return f"ERROR fetching {url}: {e}"
    ctype = r.headers.get("content-type", "")
    body = _html_to_text(r.text) if "html" in ctype else r.text
    return _clip(f"# {url}\n\n{body}")


def _ddg_unwrap(href: str) -> str:
    if "duckduckgo.com/l/" in href:
        q = parse_qs(urlparse(href).query)
        if "uddg" in q:
            return unquote(q["uddg"][0])
    return href


def web_search(query: str) -> str:
    try:
        r = httpx.post("https://html.duckduckgo.com/html/",
                       data={"q": query}, timeout=15, follow_redirects=True,
                       headers={"User-Agent": "Mozilla/5.0 (xcode)"})
        r.raise_for_status()
    except Exception as e:
        return f"ERROR searching: {e}"

    results = []
    pat = re.compile(
        r'result__a"[^>]*href="(?P<url>[^"]+)"[^>]*>(?P<title>.*?)</a>'
        r'(?:.*?result__snippet[^>]*>(?P<snip>.*?)</a>)?',
        re.IGNORECASE | re.DOTALL)
    for m in pat.finditer(r.text):
        url = _ddg_unwrap(html.unescape(m.group("url")))
        title = _html_to_text(m.group("title"))
        snip = _html_to_text(m.group("snip") or "")
        results.append(f"- {title}\n  {url}\n  {snip}".rstrip())
        if len(results) >= 6:
            break
    if not results:
        return f"(no results for '{query}')"
    return f"Results for '{query}':\n\n" + "\n\n".join(results)


def _fn(name, desc, props, required=()):
    return {"type": "function", "function": {
        "name": name, "description": desc,
        "parameters": {"type": "object", "properties": props,
                       "required": list(required)}}}


TOOL_SCHEMAS = [
    _fn("read_file", "Read a file's contents (returned with line numbers).",
        {"path": {"type": "string"}}, ["path"]),
    _fn("write_file", "Create or overwrite a file with the given full content.",
        {"path": {"type": "string"}, "content": {"type": "string"}},
        ["path", "content"]),
    _fn("edit_file",
        "Replace an exact substring in a file. old_string must match exactly "
        "once. Prefer this over write_file for small changes.",
        {"path": {"type": "string"},
         "old_string": {"type": "string", "description": "exact text to replace"},
         "new_string": {"type": "string", "description": "replacement text"}},
        ["path", "old_string", "new_string"]),
    _fn("list_dir", "List files and folders at a path (default current dir).",
        {"path": {"type": "string"}}),
    _fn("glob_files", "Find files by glob pattern, e.g. '**/*.py'.",
        {"pattern": {"type": "string"},
         "path": {"type": "string", "description": "root to search, default '.'"}},
        ["pattern"]),
    _fn("grep",
        "Search file contents by regex. Returns path:line: text matches.",
        {"pattern": {"type": "string", "description": "regular expression"},
         "path": {"type": "string", "description": "root, default '.'"},
         "glob": {"type": "string", "description": "file filter, default '**/*'"}},
        ["pattern"]),
    _fn("run_command",
        "Run a shell command; returns stdout/stderr/exit code. Set "
        "background=true for long-running things (servers, watchers) to start "
        "them detached and keep working.",
        {"command": {"type": "string"},
         "background": {"type": "boolean",
                        "description": "run detached, don't wait for it"}},
        ["command"]),
    _fn("web_search", "Search the web (DuckDuckGo). Returns titles/urls/snippets.",
        {"query": {"type": "string"}}, ["query"]),
    _fn("web_fetch", "Fetch a URL and return its text content.",
        {"url": {"type": "string"}}, ["url"]),
    _fn("spawn_agent",
        "Delegate a self-contained subtask to a fresh sub-agent with its own "
        "context. Use for big searches or isolated chunks of work. Returns the "
        "sub-agent's final report.",
        {"task": {"type": "string", "description": "what the sub-agent should do"}},
        ["task"]),
    _fn("ask_user",
        "Ask the user a clarifying question and let them pick from a short list "
        "(rendered as an arrow-key menu). Use this PROACTIVELY whenever the "
        "request is open-ended or ambiguous — call it repeatedly, one question "
        "at a time, to nail down scope, stack, hosting, naming, features, etc. "
        "before building. Returns the chosen option.",
        {"question": {"type": "string",
                      "description": "one focused question"},
         "options": {"type": "array", "items": {"type": "string"},
                     "description": "2-5 concise, distinct choices; optionally "
                                    "include a 'you decide' style option"}},
        ["question", "options"]),
    _fn("update_todos",
        "Record/update the task plan for a multi-step request.",
        {"todos": {"type": "array", "items": {"type": "object", "properties": {
            "content": {"type": "string"},
            "status": {"type": "string",
                       "enum": ["pending", "in_progress", "completed"]}},
            "required": ["content", "status"]}}},
        ["todos"]),
]


def dispatch(name: str, args: dict, confirm: Confirm, on_output: Callable[[str], None] | None = None) -> str:
    """Route a tool call from the model to the right implementation."""
    RENDER.clear()
    try:
        if name == "read_file":
            return read_file(args["path"])
        if name == "write_file":
            return write_file(args["path"], args["content"], confirm)
        if name == "edit_file":
            return edit_file(args["path"], args["old_string"],
                             args["new_string"], confirm)
        if name == "list_dir":
            return list_dir(args.get("path", "."))
        if name == "glob_files":
            return glob_files(args["pattern"], args.get("path", "."))
        if name == "grep":
            return grep(args["pattern"], args.get("path", "."),
                        args.get("glob", "**/*"))
        if name == "run_command":
            return run_command(args["command"], confirm,
                               background=bool(args.get("background", False)),
                               on_output=on_output)
        if name == "web_search":
            return web_search(args["query"])
        if name == "web_fetch":
            return web_fetch(args["url"])
        return f"ERROR: unknown tool '{name}'"
    except KeyError as e:
        return f"ERROR: tool '{name}' missing required argument {e}"
    except Exception as e:
        return f"ERROR in tool '{name}': {e}"
