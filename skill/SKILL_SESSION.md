---
name: qwen-interactive-session
description: Drive Qwen Code interactively for large, iterative projects
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [delegation, qwen, coding, interactive, session, project, iterative]
    requires_tools: [qwen_session_start, qwen_session_send, qwen_session_read, qwen_session_wait, qwen_session_stop]
    related_skills: [qwen-code-delegation]
---

# Qwen Interactive Session

## Overview

Hermes drives. Qwen builds. Turn by turn.

Unlike `qwen_task` (fire-and-forget), an interactive session gives Hermes a
live terminal connection to Qwen Code. Hermes types messages as a human would,
reads Qwen's output, assesses it, and decides what to say next — or when to
wait, correct course, or stop.

**Use this for work too large or uncertain for a single prompt.** Full project
scaffolding, multi-module features, iterative debugging sessions, exploratory
refactors — anything where Hermes needs to observe and steer rather than
delegate and hope.

**Core loop:** Start session -> Send instruction -> Wait for output -> Read
and assess -> Send next instruction (or stop).

---

## When to Use Interactive Sessions vs Task Delegation

### Use `qwen_session_start` (interactive) when:

| Signal | Examples |
|--------|----------|
| Multi-phase project | "Build a full REST API with auth, tests, and deployment" |
| Scope is unclear upfront | "Explore this codebase and refactor the worst parts" |
| Iterative course-correction | Work where each step depends on reviewing the last |
| Long-running builds/tests to monitor | "Set up CI, run the full suite, fix what breaks" |
| Teaching/pair-programming dynamic | Hermes guides Qwen step by step through a design |
| Multiple related changes in sequence | "First do X, then based on that do Y, then Z" |

### Stick with `qwen_task` (one-shot) when:

| Signal | Examples |
|--------|----------|
| Well-defined, self-contained task | "Add input validation to the signup endpoint" |
| Single prompt is enough context | "Write unit tests for the User model" |
| No need to observe intermediate state | "Rename all instances of oldName to newName" |
| Quick fix | "Fix the off-by-one error in pagination" |

---

## Step 1 — Start the Session

```python
qwen_session_start(
    working_dir="/absolute/path/to/project",
    approval_mode="yolo",       # always for automated work
    # model="...thinking"       # for complex reasoning
    # ready_timeout=60          # increase if model is slow to load
)
```

Returns a `session_id`. The session is ready when status is `"ready"`.

**Check the startup output.** If there are errors or warnings, address them
before sending the first message.

---

## Step 2 — The Interaction Loop

This is the core pattern. Repeat until the work is done:

### 2a. Send an instruction

```python
qwen_session_send(
    session_id="<id>",
    message="<clear, specific instruction>",
    idle_timeout=3.0,     # seconds of silence = Qwen is done responding
    max_wait=300,         # hard cap — partial output delivered if reached
)
```

**This call returns immediately.** It does NOT block waiting for Qwen.
After calling it, do NOT poll or call another tool — just stop and wait.
Hermes will automatically receive an inject_message notification when Qwen
finishes responding (same mechanism as qwen_task_async). When that arrives,
assess the output and decide next steps.

**Instruction quality matters more here than in one-shot tasks.** Because you
can course-correct, start with the high-level goal and refine iteratively:

```
Turn 1: "Scaffold a Flask app with blueprints for auth and api in /src"
Turn 2: "Good structure. Now add SQLAlchemy models for User and Session in src/models/"
Turn 3: "The User model needs an email unique constraint. Fix that, then add a registration endpoint."
Turn 4: "Run pytest -v and show me the output"
Turn 5: "Two tests are failing because of missing fixtures. Add a conftest.py with a test database."
```

### 2b. Wait for and assess the notification

After `qwen_session_send` returns, Hermes will receive an inject_message
notification when Qwen finishes. That notification contains the output.
Assess it:

- **Did Qwen complete the instruction?** Look for completion signals, file writes, test results.
- **Did Qwen hit an error?** Look for tracebacks, "permission denied", "not found".
- **Is the approach correct?** Even if Qwen succeeded, is it what you wanted?
- **Is there partial output?** Qwen might still be running if output looks truncated.

### 2c. Decide the next action

| Assessment | Action |
|------------|--------|
| Step complete, more steps remain | Send next instruction |
| Qwen is still processing | `qwen_session_wait(session_id, idle_timeout=5)` |
| Minor correction needed | Send correction: "Actually, change X to Y" |
| Wrong approach | Send redirect: "Stop. Take a different approach: ..." |
| Need to see current state | `qwen_session_read(session_id)` |
| All work complete | Verify, then `qwen_session_stop(session_id)` |
| Qwen is stuck/looping | `qwen_session_stop(session_id)` and start fresh |

---

## Step 3 — Waiting for Long Operations

When Qwen is running tests, building, or installing dependencies, it may take
a while. Use `qwen_session_wait` to block until output stabilizes:

```python
# After sending "run the full test suite"
qwen_session_wait(
    session_id="<id>",
    idle_timeout=5.0,    # tests may have brief pauses between files
    max_wait=600,        # 10 min for a large suite
)
```

If `timed_out` is true in the response, Qwen is still producing output. Call
`qwen_session_read` to see what's there, then decide whether to wait more.

---

## Step 4 — Reading Without Sending

Sometimes you just want to observe:

```python
# See new output since last read
qwen_session_read(session_id="<id>")

# See the full session transcript
qwen_session_read(session_id="<id>", full=True)
```

---

## Step 5 — Stopping the Session

When the work is complete (or Qwen is stuck):

```python
qwen_session_stop(session_id="<id>")
```

This sends Ctrl+C, waits, and terminates the process. **Always stop sessions
when done** — they consume resources (PTY, process, threads).

---

## Interaction Patterns

### Pattern A — Full Project Build

```
Start: "I need a FastAPI project with user auth, PostgreSQL, and Docker"

Turn 1: "Create the project structure: src/, tests/, Dockerfile, docker-compose.yml, requirements.txt. Use FastAPI + SQLAlchemy + Alembic."
Turn 2: "Add the User model with email, hashed_password, created_at. Add Alembic migration."
Turn 3: "Create auth endpoints: POST /register, POST /login (JWT), GET /me."
Turn 4: "Write tests for all three endpoints. Use pytest + httpx."
Turn 5: "Run the tests. Fix any failures."
Turn 6: "Add a Dockerfile and docker-compose.yml with a PostgreSQL service."
Turn 7: "Build and run docker-compose up. Verify the API responds on port 8000."
→ Stop
```

### Pattern B — Iterative Debugging

```
Start: "The CI pipeline is failing. Let me investigate."

Turn 1: "Run pytest tests/ -v --tb=short and show me the output"
[Read output, see 3 failures]
Turn 2: "Focus on test_user_creation. Read the test and the code it tests."
[Read output, understand the issue]
Turn 3: "The mock is wrong — it's returning a dict but the code expects a User object. Fix the mock in conftest.py"
Turn 4: "Run just test_user_creation to verify"
Turn 5: "Good. Now fix the other two failures — they look like the same pattern."
Turn 6: "Run the full suite again to confirm everything passes."
→ Stop
```

### Pattern C — Exploratory Refactor

```
Start: "This module has grown too large. Help me break it apart."

Turn 1: "Read src/monolith.py and give me a summary of its responsibilities."
[Read output — Qwen identifies 4 logical groups]
Turn 2: "Good analysis. Extract the database functions into src/db.py. Keep the imports working."
Turn 3: "Run the tests to check for breakage."
[Tests fail — circular import]
Turn 4: "Move the shared types into src/types.py to break the circular dependency."
Turn 5: "Run tests again."
Turn 6: "All passing. Now extract the API handlers into src/api.py."
Turn 7: "Tests?"
Turn 8: "Clean. Extract the remaining validation logic into src/validators.py."
Turn 9: "Final test run. Then show me the file sizes of the new modules vs the old monolith."
→ Stop
```

### Pattern D — Monitoring a Build

```
Turn 1: "Run npm install && npm run build"
[Wait with high idle_timeout since builds have long pauses]
Wait: idle_timeout=10, max_wait=600
[Read output — build succeeded with 2 warnings]
Turn 2: "Those warnings are about unused imports. Fix them."
Turn 3: "Rebuild to confirm clean output."
→ Stop
```

---

## Idle Timeout Tuning

The `idle_timeout` parameter controls how long to wait for silence before
considering Qwen "done". Tune it based on what Qwen is doing:

| Activity | Recommended idle_timeout |
|----------|--------------------------|
| Simple file edits | 2-3s (default) |
| Running quick tests | 3-5s |
| Installing packages | 5-10s |
| Running large test suites | 5-10s |
| Building / compiling | 10-15s |
| Docker operations | 10-15s |

When in doubt, use a longer idle_timeout. It's better to wait a bit extra
than to read incomplete output and act on partial results.

---

## Red Flags — Never Do These

- Start a session without `working_dir` — Qwen will operate in the wrong place
- Send vague messages ("fix it", "continue") — be specific about what to do
- Ignore error output and send the next instruction anyway
- Leave sessions running after work is done — they leak resources
- Send multiple messages without reading Qwen's response between them
- Use interactive sessions for tasks that work fine as one-shot `qwen_task`
- Assume Qwen finished just because `send` returned — check the output content
- Start many sessions at once — 3 concurrent max, prefer sequential for related work

---

## Iron Laws

```
One message at a time — always read before sending the next
Idle detection is your friend — trust it, tune it
Assess every response — never auto-accept
Stop sessions when done — always clean up
Interactive is for iteration — use one-shot for one-shot work
```

**Hermes drives the terminal. Qwen does the work. The user gets a guided, iterative build.**
