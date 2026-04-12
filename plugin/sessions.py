"""
Task and session state management for the Qwen Code bridge.

Tracks in-progress and completed Qwen tasks within a Hermes session.
Also manages a queue of results awaiting injection via pre_llm_call.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class QwenTask:
    task_id: str
    prompt: str
    status: str          # "running" | "completed" | "failed" | "timeout"
    created_at: float
    completed_at: Optional[float] = None
    session_id: Optional[str] = None
    working_dir: Optional[str] = None
    result: Optional[str] = None
    error: Optional[str] = None
    num_turns: int = 0
    duration_ms: int = 0


# In-memory store for the lifetime of the Hermes session
_tasks: Dict[str, QwenTask] = {}

# Task IDs whose results have not yet been injected into context
_pending_injection: List[str] = []


# ---------------------------------------------------------------------------
# CRUD helpers
# ---------------------------------------------------------------------------

def create_task(prompt: str, working_dir: Optional[str] = None) -> QwenTask:
    task = QwenTask(
        task_id=str(uuid.uuid4())[:8],
        prompt=prompt,
        status="running",
        created_at=time.time(),
        working_dir=working_dir,
    )
    _tasks[task.task_id] = task
    return task


def get_task(task_id: str) -> Optional[QwenTask]:
    return _tasks.get(task_id)


def list_tasks() -> List[QwenTask]:
    return sorted(_tasks.values(), key=lambda t: t.created_at, reverse=True)


def complete_task(
    task_id: str,
    result: str,
    session_id: Optional[str],
    num_turns: int,
    duration_ms: int,
) -> None:
    task = _tasks.get(task_id)
    if not task:
        return
    task.status = "completed"
    task.result = result
    task.session_id = session_id
    task.num_turns = num_turns
    task.duration_ms = duration_ms
    task.completed_at = time.time()
    _pending_injection.append(task_id)


def fail_task(task_id: str, error: str) -> None:
    task = _tasks.get(task_id)
    if not task:
        return
    task.status = "failed"
    task.error = error
    task.completed_at = time.time()
    _pending_injection.append(task_id)


# ---------------------------------------------------------------------------
# pre_llm_call helpers
# ---------------------------------------------------------------------------

def pop_pending_results() -> List[QwenTask]:
    """Drain the pending-injection queue and return the tasks."""
    items = list(_pending_injection)
    _pending_injection.clear()
    return [_tasks[tid] for tid in items if tid in _tasks]


def running_count() -> int:
    return sum(1 for t in _tasks.values() if t.status == "running")
