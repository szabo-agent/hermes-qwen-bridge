"""
Qwen Code Bridge — Hermes Agent Plugin
=======================================

Connects Hermes Agent to Qwen Code (https://github.com/QwenLM/qwen-code),
a full AI coding agent. Hermes can delegate tasks, receive results, and
continue a multi-turn collaboration with Qwen Code.

Registered tools
----------------
  qwen_task           Run a task synchronously (blocks until done)
  qwen_task_async     Start a task in background; Hermes is notified on completion
  qwen_task_status    Check status of one or all tasks
  qwen_task_result    Retrieve the stored result of a completed task
  qwen_sessions       List all tasks/sessions from this Hermes session
  qwen_check          Verify Qwen Code installation and auth

Lifecycle hooks
---------------
  pre_llm_call   — Detects coding requests and injects delegation instruction;
                   also reports running async task status
  on_session_end — Logs any tasks that were still running at shutdown
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


def _is_coding_request(message: str) -> bool:
    """Return True if the user message looks like a coding execution request."""
    if not message or not isinstance(message, str):
        return False
    text = message[:2000]  # only scan first 2000 chars
    return any(p.search(text) for p in _CODING_TRIGGERS)


# Injected when a coding request is detected. Appended to the user message
# so it appears right next to the request — harder for the model to ignore.
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
    )
    from .tools import (
        qwen_task,
        qwen_task_async,
        qwen_task_status,
        qwen_task_result,
        qwen_sessions,
        qwen_check,
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

    ctx.register_hook("pre_llm_call", _pre_llm_call_hook)
    ctx.register_hook("on_session_end", _on_session_end_hook)

    logger.info("qwen-bridge: plugin loaded — 6 tools registered")


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
    user_message = kwargs.get("user_message", "")
    if _is_coding_request(user_message):
        parts.append(_DELEGATION_REMINDER)
        logger.debug("qwen-bridge: coding request detected, injecting delegation reminder")

    # --- Async task status ---
    active = running_count()
    if active > 0:
        parts.append(
            f"[qwen-bridge] {active} Qwen Code task(s) running in background. "
            f"You will be notified on completion. Use qwen_task_status to poll."
        )

    return "\n\n".join(parts) if parts else None


def _on_session_end_hook(**kwargs) -> None:
    """Log any tasks that were still running when Hermes shut down."""
    from .sessions import list_tasks

    running = [t for t in list_tasks() if t.status == "running"]
    if running:
        ids = ", ".join(t.task_id for t in running)
        logger.warning(
            "qwen-bridge: session ended with %d Qwen task(s) still running: %s",
            len(running),
            ids,
        )
