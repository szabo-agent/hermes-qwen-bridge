"""
Qwen Code Bridge — Hermes Agent Plugin
=======================================

Connects Hermes Agent to Qwen Code (https://github.com/QwenLM/qwen-code),
a full AI coding agent. Hermes can delegate tasks, receive results, and
continue a multi-turn collaboration with Qwen Code.

Registered tools
----------------
  qwen_task             Run a task synchronously (blocks until done)
  qwen_task_async       Start a task in background; Hermes is notified on completion
  qwen_task_status      Check status of one or all tasks
  qwen_task_result      Retrieve the stored result of a completed task
  qwen_sessions         List all tasks/sessions from this Hermes session
  qwen_check            Verify Qwen Code installation and auth
  qwen_session_start    Start an interactive PTY session with Qwen Code
  qwen_session_send     Type a message into an interactive session; wait for response
  qwen_session_read     Read output from an interactive session (no send)
  qwen_session_wait     Block until interactive session output stabilizes
  qwen_session_stop     Close an interactive session
  qwen_session_list     List all interactive sessions

Lifecycle hooks
---------------
  pre_llm_call   — Detects coding requests and injects the right delegation reminder
                   (interactive session for large projects; task for focused tasks);
                   also reports running async task and interactive session status
  on_session_end — Cleans up running tasks and interactive sessions on shutdown
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Coding request detection
# ---------------------------------------------------------------------------
# These patterns match the user message text to decide whether to inject
# the delegation reminder. Ordered from most to least specific.

_CODING_TRIGGERS: list[re.Pattern] = [p for p in (re.compile(r, re.IGNORECASE | re.DOTALL) for r in [
    # "write/create/make/generate ... code/script/function/class/etc."
    r'\b(write|create|make|generate)\b.{0,60}\b(code|script|function|class|module|program|app|application|endpoint|api|test|tests|component|service|tool|plugin|daemon|cli|utility)\b',
    # "implement X"
    r'\bimplement\b.{0,80}\b(a|an|the|this|that|function|class|feature|endpoint|module|interface|method|handler|service)\b',
    # "build (me) a/the ..."
    r'\bbuild\b.{0,40}\b(a|an|me|the|this|that)\b',
    # "add a/the feature/function/method/endpoint/test"
    r'\badd\b.{0,40}\b(feature|function|method|endpoint|test|tests|class|module|handler|route|command|hook)\b',
    # "fix (the/this) bug/error/failing test"
    r'\bfix\b.{0,30}\b(bug|error|issue|test|tests|failing|broken|crash|exception|problem)\b',
    # "refactor" anything
    r'\brefactor\b',
    # "debug why/this/the"
    r'\bdebug\b.{0,30}\b(this|the|why|that|it|my)\b',
    # "set up / scaffold / bootstrap"
    r'\b(set up|scaffold|bootstrap|initialise|initialize|spin up|stub out)\b',
    # "can you write/build/code/implement"
    r'\bcan you\b.{0,30}\b(write|build|code|implement|create|make|add|fix)\b',
    # "python/js/ts/rust/go/bash script/function/class that does"
    r'\b(python|javascript|typescript|rust|go|bash|shell|ruby|java|c\+\+|c#)\b.{0,40}\b(script|function|class|program|module|snippet|that|to)\b',
])]

# Patterns that signal a LARGE / MULTI-PHASE project — use interactive session.
# Matched against the full message (up to 4000 chars) before the generic check.
_LARGE_PROJECT_TRIGGERS: list[re.Pattern] = [p for p in (re.compile(r, re.IGNORECASE | re.DOTALL) for r in [
    # Explicit "don't stop" / "keep going" / "continue until done"
    r"\b(don'?t stop|keep going|continue until|until (you'?re |it'?s )?(done|complete|finished)|as far as you can)\b",
    # Multiple features listed with conjunctions (and/,) — implies many phases
    r'\b(chat|interface|viewer|tracker|radio|ebook|wiki|dashboard|auth|login|api|frontend|backend)\b.{0,200}\b(and|,)\b.{0,200}\b(chat|interface|viewer|tracker|radio|ebook|wiki|dashboard|auth|login|api|frontend|backend)\b',
    # "full [project|app|stack|system]"
    r'\bfull\b.{0,30}\b(project|app|application|stack|system|platform|suite|website|service)\b',
    # "complete [project|app]"
    r'\bcomplete\b.{0,30}\b(project|app|application|system|platform|suite|website)\b',
    # "entire [project|codebase]"
    r'\bentire\b.{0,30}\b(project|app|codebase|system|platform|website|suite)\b',
    # "from scratch" (implies scaffolding + implementation)
    r'\bfrom scratch\b',
    # "end.to.end" or "e2e" project
    r'\bend.to.end\b|\be2e\b.{0,30}\b(app|project|system|build|setup)\b',
    # Explicitly asking for multiple named components in one request
    r'\b(include|with|has|have|featuring)\b.{0,100}\b(and|,)\b.{0,100}\b(and|,)\b.{0,100}\b(and|,)\b',
])]


def _is_coding_request(message: str) -> bool:
    """Return True if the user message looks like a coding execution request."""
    if not message or not isinstance(message, str):
        return False
    text = message[:2000]
    return any(p.search(text) for p in _CODING_TRIGGERS)


def _is_large_project(message: str) -> bool:
    """
    Return True if the message signals a large, multi-phase project that warrants
    an interactive session rather than a single qwen_task call.
    """
    if not message or not isinstance(message, str):
        return False
    text = message[:4000]
    return any(p.search(text) for p in _LARGE_PROJECT_TRIGGERS)


# Injected for large/multi-phase project requests — steers toward interactive session.
_INTERACTIVE_SESSION_REMINDER = """\

---
[qwen-bridge] LARGE MULTI-PHASE PROJECT DETECTED.
This request spans multiple components or explicitly asks you to continue until complete.
Use an INTERACTIVE SESSION, not qwen_task_async. Before doing anything:
1. Call skill_view("qwen-interactive-session") to load the interactive session guide.
2. Follow the skill — start a session with qwen_session_start, then drive it turn by turn.
Do NOT use qwen_task or qwen_task_async for this. Do NOT skip skill_view. Use interactive."""

# Injected for focused coding requests (single task, well-defined scope).
_DELEGATION_REMINDER = """\

---
[qwen-bridge] CODING TASK DETECTED.
You have the qwen_task tool available. Before writing any code yourself:
1. Call skill_view("qwen-code-delegation") to load delegation instructions.
2. Follow the skill — delegate the work to Qwen Code via qwen_task.
Do NOT produce code directly. Do NOT skip skill_view. Delegate first."""


# ---------------------------------------------------------------------------
# Plugin registration
# ---------------------------------------------------------------------------

def register(ctx) -> None:
    """Entry point called by the Hermes plugin manager at startup."""
    from .schemas import (
        QWEN_TASK_SCHEMA,
        QWEN_TASK_ASYNC_SCHEMA,
        QWEN_TASK_STATUS_SCHEMA,
        QWEN_TASK_RESULT_SCHEMA,
        QWEN_SESSIONS_SCHEMA,
        QWEN_CHECK_SCHEMA,
        QWEN_SESSION_START_SCHEMA,
        QWEN_SESSION_SEND_SCHEMA,
        QWEN_SESSION_READ_SCHEMA,
        QWEN_SESSION_WAIT_SCHEMA,
        QWEN_SESSION_STOP_SCHEMA,
        QWEN_SESSION_LIST_SCHEMA,
    )
    from .tools import (
        qwen_task,
        qwen_task_async,
        qwen_task_status,
        qwen_task_result,
        qwen_sessions,
        qwen_check,
        qwen_session_start,
        qwen_session_send,
        qwen_session_read,
        qwen_session_wait,
        qwen_session_stop,
        qwen_session_list,
        set_context_ref,
    )

    set_context_ref(ctx)

    ctx.register_tool(
        name="qwen_task",
        toolset="qwen_bridge",
        schema=QWEN_TASK_SCHEMA,
        handler=qwen_task,
        description="Run a Qwen Code task synchronously",
        emoji="🤖",
    )
    ctx.register_tool(
        name="qwen_task_async",
        toolset="qwen_bridge",
        schema=QWEN_TASK_ASYNC_SCHEMA,
        handler=qwen_task_async,
        description="Start a Qwen Code task in the background",
        emoji="⚡",
    )
    ctx.register_tool(
        name="qwen_task_status",
        toolset="qwen_bridge",
        schema=QWEN_TASK_STATUS_SCHEMA,
        handler=qwen_task_status,
        description="Check status of Qwen Code tasks",
        emoji="📊",
    )
    ctx.register_tool(
        name="qwen_task_result",
        toolset="qwen_bridge",
        schema=QWEN_TASK_RESULT_SCHEMA,
        handler=qwen_task_result,
        description="Retrieve full result of a completed Qwen Code task",
        emoji="📋",
    )
    ctx.register_tool(
        name="qwen_sessions",
        toolset="qwen_bridge",
        schema=QWEN_SESSIONS_SCHEMA,
        handler=qwen_sessions,
        description="List all Qwen Code tasks/sessions this Hermes session",
        emoji="📁",
    )
    ctx.register_tool(
        name="qwen_check",
        toolset="qwen_bridge",
        schema=QWEN_CHECK_SCHEMA,
        handler=qwen_check,
        description="Check Qwen Code installation and auth status",
        emoji="🔍",
    )

    # Interactive session tools
    ctx.register_tool(
        name="qwen_session_start",
        toolset="qwen_bridge",
        schema=QWEN_SESSION_START_SCHEMA,
        handler=qwen_session_start,
        description="Start an interactive Qwen Code session",
        emoji="🖥️",
    )
    ctx.register_tool(
        name="qwen_session_send",
        toolset="qwen_bridge",
        schema=QWEN_SESSION_SEND_SCHEMA,
        handler=qwen_session_send,
        description="Send a message to an interactive Qwen session",
        emoji="⌨️",
    )
    ctx.register_tool(
        name="qwen_session_read",
        toolset="qwen_bridge",
        schema=QWEN_SESSION_READ_SCHEMA,
        handler=qwen_session_read,
        description="Read output from an interactive Qwen session",
        emoji="👁️",
    )
    ctx.register_tool(
        name="qwen_session_wait",
        toolset="qwen_bridge",
        schema=QWEN_SESSION_WAIT_SCHEMA,
        handler=qwen_session_wait,
        description="Wait for interactive Qwen session output to stabilize",
        emoji="⏳",
    )
    ctx.register_tool(
        name="qwen_session_stop",
        toolset="qwen_bridge",
        schema=QWEN_SESSION_STOP_SCHEMA,
        handler=qwen_session_stop,
        description="Close an interactive Qwen Code session",
        emoji="⏹️",
    )
    ctx.register_tool(
        name="qwen_session_list",
        toolset="qwen_bridge",
        schema=QWEN_SESSION_LIST_SCHEMA,
        handler=qwen_session_list,
        description="List all interactive Qwen sessions",
        emoji="📋",
    )

    ctx.register_hook("pre_llm_call", _pre_llm_call_hook)
    ctx.register_hook("on_session_end", _on_session_end_hook)

    logger.info("qwen-bridge: plugin loaded — 12 tools registered (6 task, 6 interactive)")


# ---------------------------------------------------------------------------
# Hooks
# ---------------------------------------------------------------------------

def _pre_llm_call_hook(**kwargs) -> str | None:
    """
    Two responsibilities:

    1. CODING DETECTION — if the user message matches coding request patterns,
       inject a hard instruction to call skill_view and delegate before coding.
       This fires reliably on every turn regardless of whether the model would
       have voluntarily checked the skills index.

    2. ASYNC STATUS — if background Qwen tasks are running, inject a brief
       note so Hermes knows to expect a completion notification.
    """
    from .sessions import running_count

    parts: list[str] = []

    # --- Coding detection ---
    # Check large-project signals first — they take priority over the generic reminder.
    user_message = kwargs.get("user_message", "")
    if _is_large_project(user_message):
        parts.append(_INTERACTIVE_SESSION_REMINDER)
        logger.debug("qwen-bridge: large project detected, injecting interactive session reminder")
    elif _is_coding_request(user_message):
        parts.append(_DELEGATION_REMINDER)
        logger.debug("qwen-bridge: coding request detected, injecting delegation reminder")

    # --- Async task status ---
    active = running_count()
    if active > 0:
        parts.append(
            f"[qwen-bridge] {active} Qwen Code task(s) running in background. "
            f"You will be notified on completion. Use qwen_task_status to poll."
        )

    # --- Interactive session status ---
    from .interactive import active_session_count
    interactive = active_session_count()
    if interactive > 0:
        parts.append(
            f"[qwen-bridge] {interactive} interactive Qwen session(s) active. "
            f"Use qwen_session_send to interact, qwen_session_read to check output."
        )

    return "\n\n".join(parts) if parts else None


def _on_session_end_hook(**kwargs) -> None:
    """Log and clean up any tasks/sessions still running when Hermes shuts down."""
    from .sessions import list_tasks
    from .interactive import list_sessions, stop_session

    running = [t for t in list_tasks() if t.status == "running"]
    if running:
        ids = ", ".join(t.task_id for t in running)
        logger.warning(
            "qwen-bridge: session ended with %d Qwen task(s) still running: %s",
            len(running),
            ids,
        )

    # Clean up interactive sessions
    active = [s for s in list_sessions() if s.status in ("starting", "ready", "busy")]
    for s in active:
        logger.warning("qwen-bridge: stopping interactive session %s on shutdown", s.session_id)
        try:
            stop_session(s.session_id)
        except Exception as exc:
            logger.error("qwen-bridge: error stopping session %s: %s", s.session_id, exc)
