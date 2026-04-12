---
name: qwen-code-delegation
description: Write/implement/build/refactor/debug code → Qwen Code
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [delegation, qwen, coding, implementation, refactor, debugging, testing]
    requires_tools: [qwen_task, qwen_task_async]
    related_skills: [subagent-driven-development, systematic-debugging, writing-plans, test-driven-development]
---

# Qwen Code Delegation

## Overview

Hermes orchestrates. Qwen Code executes.

Qwen Code is a full coding agent running the local Qwen3-Coder-30B model. It has its own tool loop: it can read and write files, run shell commands, install packages, run tests, and iterate on errors — all inside its session. Hermes' role is to delegate clearly, then assess what comes back and decide what happens next.

**Core principle:** Give Qwen everything it needs in one prompt. Assess the output critically. Continue the session or escalate — never silently accept incomplete work.

---

## Step 1 — Delegate or Self-Execute?

Apply this decision before every coding request.

### Delegate to Qwen when the task involves:

| Signal | Examples |
|--------|---------|
| Multi-file changes | Adding a feature across models + routes + tests |
| Write-run-fix cycles | "Implement X and make the tests pass" |
| Shell execution as part of coding | Install deps, run builds, migrate DB, run benchmarks |
| Refactoring across a codebase | Rename, restructure, extract patterns across many files |
| Full feature or module from scratch | "Build a REST endpoint for user registration" |
| Debugging that needs iteration | Run → see error → fix → re-run |
| Any task > ~30 lines or > 2 files | Size alone is a signal |
| Test suite authoring | Write comprehensive tests for existing code |
| Git workflows embedded in coding | Commit, branch, rebase during implementation |

**Trigger phrases:** "write", "build", "implement", "create", "add feature", "refactor", "fix bug", "make tests pass", "set up", "scaffold", "migrate", "add tests"

### Handle yourself (Hermes) when:

| Signal | Examples |
|--------|---------|
| Explanation only | "What does this function do?" |
| Single snippet < 20 lines, no run needed | "Write a regex for email validation" |
| Config or YAML edits | Edit a single config value |
| Documentation changes | Update a README section |
| User is asking, not asking you to act | "Is X a good pattern?" |

**When in doubt, delegate.** Qwen Code has full shell access and will not break things unnecessarily in `yolo` mode.

---

## Step 2 — Gather Context Before Delegating

Always collect these before calling `qwen_task`:

```
1. working_dir  — where should Qwen operate?
   - Ask the user if not clear, or check cwd via terminal
   - ALWAYS pass working_dir explicitly; never leave it to chance

2. Relevant files — what does Qwen need to know about upfront?
   - Read key files (entry points, related modules, test structure)
   - Summarise in the prompt; don't make Qwen discover structure from scratch

3. Constraints — language version, framework, style, test runner
   - E.g. "Python 3.11, pytest, follow existing naming conventions in src/"

4. Verification — how will Qwen (and you) know it worked?
   - E.g. "all pytest tests in tests/ must pass", "git status should be clean"
```

---

## Step 3 — Choose Sync vs Async

| Use `qwen_task` (sync) | Use `qwen_task_async` (async) |
|------------------------|-------------------------------|
| Task likely < 5 min | Task likely > 5 min |
| Single focused change | Large refactor, full feature |
| Quick bug fix | Running a full test suite |
| You want the result inline | You want to continue other work |
| User is waiting for a direct answer | Long builds or migrations |

For async tasks: tell the user Qwen is running in background, then wait for the inject_message notification before assessing.

---

## Step 4 — Choose Thinking Mode

| Use default model | Use thinking model |
|-------------------|--------------------|
| Straightforward implementation | Complex algorithm design |
| Clear spec, just needs coding | Architectural decisions |
| Bug with obvious fix | Debugging subtle concurrency issues |
| Routine refactor | Multi-step reasoning about trade-offs |

To enable thinking: pass `model="Qwen3-Coder-30B-A3B-Instruct-UD-Q4_K_XL.gguf__thinking"` to `qwen_task`.

---

## Step 5 — Construct the Prompt

A good Qwen prompt has four parts. Always include all four.

```
[TASK]
One clear sentence describing what to build or fix.

[CONTEXT]
- Working directory: /absolute/path/to/project
- Relevant files and their purpose (brief summary, not full content)
- Framework/language/toolchain
- Any conventions to follow (naming, structure, style)
- Related code the task touches

[REQUIREMENTS]
- Explicit list of what must be true when done
- File paths that must exist/change
- Functions/classes/endpoints to create
- Behaviours to implement
- Constraints (no new dependencies, keep existing tests passing, etc.)

[VERIFICATION]
- Exact command(s) to confirm success
- Expected output or exit code
- What "done" looks like
```

**Prompt template:**

```
Implement [TASK] in [working_dir].

Context:
- [framework/language/version]
- [key files and their roles]
- [conventions to follow]

Requirements:
- [requirement 1]
- [requirement 2]
- ...

Verify by running:
  [command]
Expected: [outcome]

Do not modify files outside [scope]. Commit when done with message: "[commit message]"
```

---

## Step 6 — Call qwen_task

```python
qwen_task(
    prompt="<constructed prompt from Step 5>",
    working_dir="/absolute/path/to/project",
    approval_mode="yolo",       # always for automated coding
    # session_id="<id>"         # only if continuing a previous session
    # model="...thinking"       # only for complex reasoning (Step 4)
    # timeout=300               # increase for long tasks
)
```

---

## Step 7 — Assess the Output

When `qwen_task` returns (or inject_message fires for async), apply this checklist before responding to the user:

### 7a. Completion check
- [ ] Did the result field contain actual code/output or just an error?
- [ ] Does the output address ALL requirements from the prompt?
- [ ] Is `is_error: false`?

### 7b. Verification check
- If Qwen ran the verification command: did it pass?
- If Qwen did NOT run the verification command: run it yourself via terminal
- Never tell the user "done" before verification

### 7c. Quality scan
Read the result text for these red flags:
- "I couldn't", "I was unable to", "permission denied" → Qwen hit a wall
- "TODO", "placeholder", "left as exercise" → incomplete work
- Error tracebacks without a fix → Qwen gave up
- File path doesn't exist after Qwen claimed to write it → silent failure

### 7d. Decide next action

| Assessment result | Action |
|-------------------|--------|
| Complete and verified | Report to user with summary |
| Partially complete — clear next step | Continue same session (pass `session_id`) |
| Qwen hit an error and stopped | Continue session with error context |
| Wrong approach taken | Start fresh session with corrected prompt |
| Fundamental misunderstanding | Handle yourself or rewrite the prompt entirely |
| Qwen timed out | Break task into smaller pieces, re-delegate |

---

## Step 8 — Continuing a Session

When Qwen's output is partial or needs follow-up, reuse the session instead of starting fresh. The session retains Qwen's tool call history and file state.

```python
# Get session_id from previous qwen_task result
qwen_task(
    prompt="The previous implementation is missing the error handling in register_user(). "
           "Add try/except for IntegrityError (duplicate email) and return 409. "
           "Re-run: pytest tests/test_auth.py -v",
    working_dir="/path/to/project",
    session_id="<session_id from prior result>",
    approval_mode="yolo",
)
```

**When to continue vs start fresh:**
- Continue: same task, partial completion, fixing errors Qwen encountered
- Fresh: different task, Qwen went off-track, approach was fundamentally wrong

---

## Step 9 — Report to User

After verified completion:

```
Report:
1. What was done (1-3 sentences, concrete)
2. Files changed (list with brief purpose)
3. Verification result (test output, build result, etc.)
4. Session ID (if user may want to continue or reference it)

Do NOT:
- Paste Qwen's full output verbatim — summarise it
- Report "done" without having verified
- Omit the session ID (useful for follow-up)
```

---

## Common Task Patterns

### Pattern A — New Feature

```
Trigger: "add X feature", "implement Y", "build Z"

1. Read the relevant existing code (entry points, models, routes)
2. Construct prompt with full context + requirements + test verification
3. qwen_task(sync if < 5 min, async otherwise)
4. Assess: verify tests pass, check files created
5. If partial: continue session with specific gap
6. Report: files changed, tests passing, session ID
```

### Pattern B — Bug Fix

```
Trigger: "fix", "broken", "error", "failing test", "wrong behavior"

1. Read the error or failing test output first
2. Identify the file(s) involved
3. Prompt: describe the bug, include error output, require a regression test
4. qwen_task(sync, thinking mode if subtle)
5. Assess: does the fix address root cause? regression test added?
6. If Qwen guessed: continue session asking for root cause first
7. Report: what the bug was, what the fix was, regression test added
```

### Pattern C — Refactor

```
Trigger: "refactor", "clean up", "restructure", "rename", "extract"

1. Identify scope (which files/modules are in bounds)
2. State what must NOT change (public API, test behaviour)
3. qwen_task_async (refactors are often large)
4. When result arrives: verify tests still pass, no regressions
5. If tests broke: continue session to fix
6. Report: what changed, what didn't, test status
```

### Pattern D — Tests

```
Trigger: "write tests", "add tests", "test coverage", "make tests pass"

1. Identify what's being tested and where tests live
2. Include test runner and convention (pytest, unittest, jest, etc.)
3. Prompt: require RED test first, then GREEN — enforce TDD
4. qwen_task(sync for small suites, async for large)
5. Assess: tests actually run and pass? No trivially-passing tests?
6. Report: N tests added, coverage area, all passing
```

### Pattern E — Setup / Scaffold

```
Trigger: "set up", "scaffold", "initialise", "bootstrap", "create project"

1. Confirm target directory and tech stack
2. qwen_task_async (setup tasks always take time)
3. When done: spot-check key generated files, verify build/run command works
4. Report: structure created, how to run it
```

---

## Red Flags — Never Do These

- Delegate without `working_dir` — Qwen will operate in the wrong directory
- Accept Qwen output without running verification yourself
- Tell the user "done" before verifying
- Start a fresh session when continuation is better (wastes context)
- Pass a vague prompt ("fix the auth stuff") — be specific
- Ignore "I couldn't" / error messages in Qwen's output
- Delegate an explanation-only task — Qwen will write files for something that needed a text answer
- Use thinking mode for routine tasks — it adds 30-60s with no benefit
- Forget to pass `session_id` when you clearly need continuity

---

## Iron Laws

```
working_dir is mandatory
Verify before reporting done
Assess critically — do not auto-accept
session_id enables continuity — use it
Vague prompts produce vague code
```

**Qwen executes. Hermes judges. The user gets verified, working code.**
