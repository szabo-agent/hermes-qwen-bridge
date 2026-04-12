"""
Tool handler implementations for the Qwen Code bridge.

All handlers follow the Hermes convention:
  handler(args: dict, **kwargs) -> str   (always returns JSON string, never raises)
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import List, Optional

from .sessions import (
    QwenTask,
    complete_task,
    create_task,
    fail_task,
    get_task,
    list_tasks,
    running_count,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Local model defaults — matches ~/.qwen/settings.json
# ---------------------------------------------------------------------------

DEFAULT_MODEL = "Qwen3-Coder-30B-A3B-Instruct-UD-Q4_K_XL.gguf"
DEFAULT_AUTH_TYPE = "openai"

# Timeout defaults tuned for Qwen3-Coder-30B running locally at ~66 tok/s.
# The model generates fast, but Qwen Code tasks involve multiple LLM turns
# (plan → write → run → fix) and shell execution time on top.
#   Simple tasks  (1–3 tool calls):   40–90s
#   Moderate tasks (4–10 tool calls):  2–5 min
#   Complex tasks  (tests, iteration): 5–15 min
# qwen_task (sync) covers up to complex; qwen_task_async covers large refactors.
DEFAULT_SYNC_TIMEOUT = 900    # 15 min  — sync tasks
DEFAULT_ASYNC_TIMEOUT = 1800  # 30 min  — background tasks

# Set by __init__.py after registration so async threads can inject_message.
_ctx_ref = None


def set_context_ref(ctx) -> None:
    global _ctx_ref
    _ctx_ref = ctx


# ---------------------------------------------------------------------------
# Qwen binary discovery
# ---------------------------------------------------------------------------

def _find_qwen() -> Optional[str]:
    """Return the path to the qwen binary, or None if not found."""
    # 1. Plain PATH lookup
    found = shutil.which("qwen")
    if found:
        return found

    # 2. Common user-local install paths
    candidates = [
        Path.home() / ".local" / "bin" / "qwen",
        Path.home() / ".npm-global" / "bin" / "qwen",
        Path.home() / ".npm" / "bin" / "qwen",
        Path("/usr/local/bin/qwen"),
        Path("/usr/bin/qwen"),
    ]
    for p in candidates:
        if p.exists() and p.is_file():
            return str(p)

    return None


def _qwen_cmd(args_dict: dict, extra_flags: Optional[List[str]] = None) -> List[str]:
    """Build the qwen CLI invocation from tool args, always using stream-json output.

    Auth type and model default to the local llama-cpp instance configured in
    ~/.qwen/settings.json.  Both can be overridden per-call via args_dict.
    """
    qwen_bin = _find_qwen()
    if qwen_bin:
        cmd: List[str] = [qwen_bin]
    else:
        # Fall back to npx — will download on first run
        cmd = ["npx", "--yes", "@qwen-code/qwen-code"]

    prompt = args_dict.get("prompt", "")
    approval_mode = args_dict.get("approval_mode", "yolo")

    # Always pin auth-type and model explicitly so headless invocations
    # don't depend on persisted /model state from an interactive session.
    model = args_dict.get("model") or DEFAULT_MODEL
    auth_type = args_dict.get("auth_type") or DEFAULT_AUTH_TYPE

    cmd += [
        "-p", prompt,
        "--output-format", "stream-json",
        "--approval-mode", approval_mode,
        "--auth-type", auth_type,
        "--model", model,
    ]

    system_prompt = args_dict.get("system_prompt")
    if system_prompt:
        cmd += ["--system-prompt", system_prompt]

    append_prompt = args_dict.get("append_system_prompt")
    if append_prompt:
        cmd += ["--append-system-prompt", append_prompt]

    session_id = args_dict.get("session_id")
    if session_id:
        cmd += ["--resume", session_id]

    allowed_tools = args_dict.get("allowed_tools")
    if allowed_tools:
        cmd += ["--allowed-tools"] + list(allowed_tools)

    exclude_tools = args_dict.get("exclude_tools")
    if exclude_tools:
        cmd += ["--exclude-tools"] + list(exclude_tools)

    if extra_flags:
        cmd += extra_flags

    return cmd


# ---------------------------------------------------------------------------
# Output parsing
# ---------------------------------------------------------------------------

def _parse_stream_json(raw: str) -> dict:
    """
    Parse Qwen Code's stream-json NDJSON output into a structured dict.

    Returns:
        {
            "text_parts": [str, ...],    # All assistant text blocks in order
            "tool_calls": [{"name": str, "input": dict}, ...],
            "session_id": str | None,
            "result": {isError, numTurns, durationMs, errorMessage} | None,
        }
    """
    text_parts: List[str] = []
    tool_calls: List[dict] = []
    session_id = None
    result_obj = None

    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue

        msg_type = obj.get("type")

        if msg_type == "assistant":
            if not session_id:
                session_id = obj.get("session_id")
            message = obj.get("message", {})
            for block in message.get("content", []):
                btype = block.get("type")
                if btype == "text":
                    txt = block.get("text", "").strip()
                    if txt:
                        text_parts.append(txt)
                elif btype == "tool_use":
                    tool_calls.append({
                        "name": block.get("name", ""),
                        "input": block.get("input", {}),
                    })

        elif msg_type == "result":
            result_obj = obj
            if not session_id:
                session_id = obj.get("session_id")

    return {
        "text_parts": text_parts,
        "tool_calls": tool_calls,
        "session_id": session_id,
        "result": result_obj,
    }


def _format_output(parsed: dict, include_tools: bool = True) -> str:
    """Convert parsed Qwen output into a human-readable string for Hermes."""
    parts: List[str] = []

    if include_tools and parsed["tool_calls"]:
        tool_summary = ", ".join(
            tc["name"] for tc in parsed["tool_calls"]
        )
        parts.append(f"[Tools used: {tool_summary}]")

    parts.extend(parsed["text_parts"])

    result = parsed.get("result")
    if result:
        # Qwen Code 0.14+ uses snake_case; older versions used camelCase
        is_error = result.get("is_error") or result.get("isError") or False
        err_msg = result.get("error_message") or result.get("errorMessage")
        turns = result.get("num_turns") or result.get("numTurns") or 0
        ms = result.get("duration_ms") or result.get("durationMs") or 0
        if is_error:
            parts.append(f"\n[Qwen Code error: {err_msg or 'Unknown error'}]")
        else:
            parts.append(f"\n[Completed — {turns} turns, {ms / 1000:.1f}s]")

    return "\n\n".join(p for p in parts if p)


# ---------------------------------------------------------------------------
# Async worker
# ---------------------------------------------------------------------------

def _async_worker(task_id: str, cmd: List[str], cwd: Optional[str], timeout: int) -> None:
    """Background thread: run Qwen Code and inject the result back into Hermes."""
    logger.debug("qwen-bridge: starting async task %s — %s", task_id, cmd[:4])
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd or None,
        )
        parsed = _parse_stream_json(proc.stdout or "")
        result_text = _format_output(parsed)

        # Handle non-zero exit with no usable output
        if not result_text and proc.returncode != 0:
            result_text = proc.stderr[:1000] if proc.stderr else f"Exit code {proc.returncode}"

        res = parsed.get("result") or {}
        complete_task(
            task_id=task_id,
            result=result_text,
            session_id=parsed.get("session_id"),
            num_turns=res.get("num_turns") or res.get("numTurns") or 0,
            duration_ms=res.get("duration_ms") or res.get("durationMs") or 0,
        )
        task = get_task(task_id)

        if _ctx_ref:
            session_info = f"session_id={task.session_id}" if task.session_id else "no session"
            inject = (
                f"[Qwen Code task `{task_id}` completed ({session_info}, "
                f"{task.num_turns} turns, {task.duration_ms / 1000:.1f}s)]\n\n"
                f"{result_text}\n\n"
                f"Please review the above output and decide on next steps."
            )
            _ctx_ref.inject_message(inject, role="user")

    except subprocess.TimeoutExpired:
        fail_task(task_id, f"Timed out after {timeout}s")
        logger.warning("qwen-bridge: task %s timed out", task_id)
        if _ctx_ref:
            _ctx_ref.inject_message(
                f"[Qwen Code task `{task_id}` timed out after {timeout}s. "
                f"Use qwen_task_result to inspect any partial output captured before the timeout.]",
                role="user",
            )

    except Exception as exc:
        fail_task(task_id, f"{type(exc).__name__}: {exc}")
        logger.exception("qwen-bridge: async task %s failed", task_id)
        if _ctx_ref:
            _ctx_ref.inject_message(
                f"[Qwen Code task `{task_id}` failed: {type(exc).__name__}: {exc}]",
                role="user",
            )


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------

def qwen_task(args: dict, **kwargs) -> str:
    """Synchronous: run Qwen Code and block until done."""
    prompt = (args.get("prompt") or "").strip()
    if not prompt:
        return json.dumps({"error": "prompt is required"})

    timeout = int(args.get("timeout") or DEFAULT_SYNC_TIMEOUT)
    working_dir = args.get("working_dir") or None

    cmd = _qwen_cmd(args)
    logger.debug("qwen-bridge: sync task — %s", cmd[:4])

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=working_dir,
        )
    except subprocess.TimeoutExpired:
        return json.dumps({"error": f"Qwen Code timed out after {timeout}s"})
    except FileNotFoundError:
        return json.dumps({
            "error": "Qwen Code binary not found",
            "fix": "Install with: npm install -g @qwen-code/qwen-code",
        })
    except Exception as exc:
        return json.dumps({"error": str(type(exc).__name__), "detail": str(exc)})

    if proc.returncode != 0 and not proc.stdout.strip():
        return json.dumps({
            "error": "Qwen Code process exited non-zero with no output",
            "stderr": (proc.stderr or "")[:500],
            "returncode": proc.returncode,
        })

    parsed = _parse_stream_json(proc.stdout or "")
    result_text = _format_output(parsed)
    res = parsed.get("result") or {}

    return json.dumps({
        "status": "completed",
        "result": result_text,
        "session_id": parsed.get("session_id"),
        "num_turns": res.get("num_turns") or res.get("numTurns") or 0,
        "duration_ms": res.get("duration_ms") or res.get("durationMs") or 0,
        "is_error": res.get("is_error") or res.get("isError") or False,
        "error_message": res.get("error_message") or res.get("errorMessage"),
    }, ensure_ascii=False)


def qwen_task_async(args: dict, **kwargs) -> str:
    """Asynchronous: start Qwen Code in background, return task_id immediately."""
    prompt = (args.get("prompt") or "").strip()
    if not prompt:
        return json.dumps({"error": "prompt is required"})

    timeout = int(args.get("timeout") or DEFAULT_ASYNC_TIMEOUT)
    working_dir = args.get("working_dir") or None

    cmd = _qwen_cmd(args)
    task = create_task(prompt=prompt, working_dir=working_dir)

    thread = threading.Thread(
        target=_async_worker,
        args=(task.task_id, cmd, working_dir, timeout),
        daemon=True,
        name=f"qwen-{task.task_id}",
    )
    thread.start()
    logger.info("qwen-bridge: launched async task %s", task.task_id)

    return json.dumps({
        "status": "started",
        "task_id": task.task_id,
        "message": (
            f"Qwen Code task `{task.task_id}` is running in the background "
            f"(timeout: {timeout}s). Hermes will be notified automatically "
            f"when it completes. Use qwen_task_status to poll."
        ),
    })


def qwen_task_status(args: dict, **kwargs) -> str:
    """Return status of one or all tasks."""
    task_id = (args.get("task_id") or "").strip()

    if task_id:
        task = get_task(task_id)
        if not task:
            return json.dumps({"error": f"Task {task_id!r} not found"})
        return json.dumps({
            "task_id": task.task_id,
            "status": task.status,
            "prompt": task.prompt,
            "working_dir": task.working_dir,
            "session_id": task.session_id,
            "num_turns": task.num_turns,
            "duration_ms": task.duration_ms,
            "error": task.error,
            "created_at": time.strftime("%H:%M:%S", time.localtime(task.created_at)),
            "completed_at": (
                time.strftime("%H:%M:%S", time.localtime(task.completed_at))
                if task.completed_at else None
            ),
        })

    # List all
    tasks = list_tasks()
    if not tasks:
        return json.dumps({"message": "No Qwen Code tasks in this session"})

    return json.dumps({
        "tasks": [
            {
                "task_id": t.task_id,
                "status": t.status,
                "prompt_preview": (t.prompt[:80] + "…") if len(t.prompt) > 80 else t.prompt,
                "session_id": t.session_id,
                "created_at": time.strftime("%H:%M:%S", time.localtime(t.created_at)),
            }
            for t in tasks
        ]
    })


def qwen_task_result(args: dict, **kwargs) -> str:
    """Return the full stored result for a completed task."""
    task_id = (args.get("task_id") or "").strip()
    if not task_id:
        return json.dumps({"error": "task_id is required"})

    task = get_task(task_id)
    if not task:
        return json.dumps({"error": f"Task {task_id!r} not found"})

    if task.status == "running":
        return json.dumps({"status": "running", "message": "Task is still in progress"})

    return json.dumps({
        "task_id": task.task_id,
        "status": task.status,
        "result": task.result,
        "error": task.error,
        "session_id": task.session_id,
        "num_turns": task.num_turns,
        "duration_ms": task.duration_ms,
        "working_dir": task.working_dir,
        "prompt": task.prompt,
    }, ensure_ascii=False)


def qwen_sessions(args: dict, **kwargs) -> str:
    """List all Qwen Code tasks/sessions from this Hermes session."""
    tasks = list_tasks()
    if not tasks:
        return json.dumps({"message": "No Qwen Code tasks in this session yet"})

    return json.dumps({
        "tasks": [
            {
                "task_id": t.task_id,
                "status": t.status,
                "session_id": t.session_id,
                "working_dir": t.working_dir,
                "num_turns": t.num_turns,
                "duration_ms": t.duration_ms,
                "prompt": t.prompt,
            }
            for t in tasks
        ]
    }, ensure_ascii=False)


def qwen_check(args: dict, **kwargs) -> str:
    """Check Qwen Code installation and authentication status."""
    qwen_bin = _find_qwen()

    info: dict = {"installed": bool(qwen_bin), "binary": qwen_bin}

    if qwen_bin:
        try:
            r = subprocess.run(
                [qwen_bin, "--version"],
                capture_output=True, text=True, timeout=10,
            )
            info["version"] = r.stdout.strip() or r.stderr.strip()
        except Exception as exc:
            info["version_error"] = str(exc)
    else:
        # Check npx availability
        npx = shutil.which("npx")
        info["npx_available"] = bool(npx)
        info["install_command"] = "npm install -g @qwen-code/qwen-code"

    # Check auth / settings
    settings_candidates = [
        Path.home() / ".qwen" / "settings.json",
        Path.cwd() / ".qwen" / "settings.json",
    ]
    for sp in settings_candidates:
        if sp.exists():
            info["settings_file"] = str(sp)
            try:
                import json as _json
                data = _json.loads(sp.read_text())
                # Mask API key values
                masked = {
                    k: ("***" if "key" in k.lower() or "token" in k.lower() else v)
                    for k, v in data.items()
                }
                info["settings"] = masked
            except Exception:
                info["settings"] = "(unreadable)"
            break
    else:
        info["settings_file"] = None
        info["hint"] = (
            "No ~/.qwen/settings.json found. "
            "Run 'qwen' interactively once to complete authentication setup, "
            "or create settings.json manually with your API key."
        )

    info["running_tasks"] = running_count()
    return json.dumps(info, indent=2)
