# hermes-qwen-bridge

A Hermes Agent plugin that bridges to [Qwen Code](https://github.com/QwenLM/qwen-code), delegating coding tasks from Hermes to a full AI coding agent and returning results for assessment.

## What it does

When you ask Hermes to write, build, fix, refactor, or test code, the bridge:

1. Detects the coding request via a `pre_llm_call` hook
2. Injects a delegation reminder into the turn so Hermes loads the skill
3. Hermes calls `qwen_task` (sync) or `qwen_task_async` (background)
4. Qwen Code runs its full agentic loop — reading/writing files, running commands, searching code
5. The complete output is returned to Hermes for assessment and next steps

## Requirements

- [Hermes Agent](https://github.com/42-evey/hermes-agent) installed and configured
- [Qwen Code](https://github.com/QwenLM/qwen-code) installed: `npm install -g @qwen-code/qwen-code`
- A running OpenAI-compatible inference server (e.g. llama-cpp-python) with a Qwen3-Coder model

## Installation

```bash
git clone https://github.com/yourname/hermes-qwen-bridge
cd hermes-qwen-bridge
./install.sh
```

Re-run at any time — existing symlinks are updated, existing configs are not overwritten unless you pass `--force`.

### What the installer does

| Step | Action |
|------|--------|
| 1 | Symlinks `plugin/` → `~/.hermes/plugins/qwen-bridge` |
| 2 | Symlinks `skill/SKILL.md` → `~/.hermes/skills/software-development/qwen-code-delegation/SKILL.md` |
| 3 | Copies `config/qwen-settings.json` → `~/.qwen/settings.json` (skip if exists) |
| 4 | Appends `- qwen_bridge` to toolsets in `~/.hermes/config.yaml` |
| 5 | Checks that `qwen` is in PATH |

### Force overwrite

```bash
./install.sh --force   # replace existing directory/file installs and overwrite qwen settings
```

### Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `HERMES_HOME` | `~/.hermes` | Hermes config directory |
| `QWEN_HOME` | `~/.qwen` | Qwen Code config directory |

## Configuration

### Qwen Code model

The plugin defaults to `Qwen3-Coder-30B-A3B-Instruct-UD-Q4_K_XL.gguf` at `http://localhost:8082/v1`.

Edit `~/.qwen/settings.json` (or `config/qwen-settings.json` before first install) to change the model ID, endpoint, or sampling parameters.

Two model entries are pre-configured:

| Model ID | Thinking | Use for |
|----------|----------|---------|
| `Qwen3-Coder-30B-A3B-Instruct-UD-Q4_K_XL.gguf` | off | Standard tasks — faster |
| `Qwen3-Coder-30B-A3B-Instruct-UD-Q4_K_XL.gguf__thinking` | on | Complex multi-step reasoning |

### Timeouts

| Setting | Default | Notes |
|---------|---------|-------|
| `qwen_task` timeout | 900 s (15 min) | Pass `timeout` arg to override |
| `qwen_task_async` timeout | 1800 s (30 min) | Pass `timeout` arg to override |
| Qwen Code `generationConfig.timeout` | 900 000 ms | In `~/.qwen/settings.json` |

## Tools

Six tools are registered under the `qwen_bridge` toolset:

### `qwen_task`

Run a task synchronously. Blocks until Qwen Code finishes.

```
prompt          (required) Task description — be specific and complete
working_dir     Absolute path for Qwen Code to operate in
approval_mode   yolo | auto-edit | default | plan  (default: yolo)
system_prompt   Override Qwen Code's system prompt
append_system_prompt  Append to default system prompt
session_id      Resume a previous session
model           Override model (use __thinking suffix for thinking mode)
auth_type       Override auth type (default: openai)
allowed_tools   Restrict to these Qwen Code tools
exclude_tools   Prevent use of these Qwen Code tools
timeout         Max seconds to wait (default: 900)
```

### `qwen_task_async`

Start a task in the background. Hermes is notified on completion.

Same parameters as `qwen_task`, with `timeout` default 1800 s.

### `qwen_task_status`

Check task status or list all tasks.

```
task_id   (optional) Omit to list all tasks this session
```

Status values: `running` | `completed` | `failed` | `timeout`

### `qwen_task_result`

Retrieve the full output of a completed task.

```
task_id   (required) Task to retrieve
```

### `qwen_sessions`

List all tasks and sessions from the current Hermes session, including session IDs for continuation.

### `qwen_check`

Verify Qwen Code installation, binary location, and auth configuration.

## Skill: qwen-code-delegation

The skill at `~/.hermes/skills/software-development/qwen-code-delegation/SKILL.md` tells Hermes when and how to delegate:

- **When to delegate**: implement/write/build/refactor/debug/test tasks, multi-file changes, test suites
- **When to handle directly**: quick explanations, single-line fixes, non-code questions
- **Prompt template**: structured `[TASK] / [CONTEXT] / [REQUIREMENTS] / [VERIFICATION]` sections
- **Assessment checklist**: completion, verification, quality, next action
- **Thinking mode**: triggered automatically for complex multi-step reasoning tasks

The skill is only surfaced when `qwen_task` and `qwen_task_async` are available (controlled by `requires_tools` in frontmatter).

## Delegation trigger

The `pre_llm_call` hook scans user messages for coding request patterns before every LLM call. When detected, it appends a hard instruction to load the delegation skill — bypassing the model's tendency to generate code directly without checking skills.

Detected patterns include:

- `write/create/make/generate ... code/script/function/class/...`
- `implement a/the feature/endpoint/...`
- `build (me) a/the ...`
- `add a/the feature/function/endpoint/test/...`
- `fix (the/this) bug/error/failing test/...`
- `refactor ...`
- `debug why/this/...`
- `set up / scaffold / bootstrap / initialize ...`
- `can you write/build/code/implement/...`
- language + artifact patterns (e.g. `python script that ...`)

## Project layout

```
hermes-qwen-bridge/
├── plugin/               Hermes plugin source (symlinked to ~/.hermes/plugins/qwen-bridge)
│   ├── plugin.yaml       Plugin manifest
│   ├── __init__.py       register(ctx), hooks, coding detection
│   ├── tools.py          Tool handlers (qwen_task, qwen_task_async, etc.)
│   ├── sessions.py       In-memory task/session state
│   └── schemas.py        OpenAI function-call schemas
├── skill/
│   └── SKILL.md          Delegation skill (symlinked into ~/.hermes/skills/)
├── config/
│   └── qwen-settings.json  Reference Qwen Code settings
├── docs/                 Extended documentation (to come)
└── install.sh            Installer script
```

## License

MIT
