"""
OpenAI function-calling schemas for all Qwen Code bridge tools.
"""

QWEN_TASK_SCHEMA = {
    "name": "qwen_task",
    "description": (
        "Delegate a coding task to Qwen Code and wait for the result. "
        "Qwen Code is a full AI coding agent: it can read/write files, run terminal commands, "
        "search code, install packages, debug programs, and more.\n\n"
        "Use this tool when you want to:\n"
        "- Offload a well-defined coding or file-editing task to Qwen Code\n"
        "- Have Qwen Code implement a feature, write tests, or refactor code\n"
        "- Run a task in a specific working directory\n\n"
        "This call BLOCKS until Qwen Code finishes (up to `timeout` seconds). "
        "For long-running tasks, prefer `qwen_task_async` so Hermes is not blocked."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "The task or question to send to Qwen Code. Be specific and complete.",
            },
            "working_dir": {
                "type": "string",
                "description": (
                    "Absolute path to the directory Qwen Code should operate in. "
                    "Defaults to the current working directory."
                ),
            },
            "approval_mode": {
                "type": "string",
                "enum": ["yolo", "auto-edit", "default", "plan"],
                "description": (
                    "Permission mode for Qwen Code tool use.\n"
                    "- yolo: approve all actions automatically (recommended for automation)\n"
                    "- auto-edit: auto-approve file edits, prompt for other tools\n"
                    "- default: standard interactive approval\n"
                    "- plan: plan-only, no execution"
                ),
                "default": "yolo",
            },
            "system_prompt": {
                "type": "string",
                "description": (
                    "Optional system prompt to prepend to the Qwen Code session. "
                    "Use this to set context, style guidelines, or constraints."
                ),
            },
            "append_system_prompt": {
                "type": "string",
                "description": "Additional instructions to append to Qwen Code's default system prompt.",
            },
            "session_id": {
                "type": "string",
                "description": (
                    "Resume a previous Qwen Code session by its session ID. "
                    "Get session IDs from qwen_sessions or previous qwen_task results."
                ),
            },
            "model": {
                "type": "string",
                "description": (
                    "Override the model. Defaults to Qwen3-Coder-30B-A3B-Instruct-UD-Q4_K_XL.gguf "
                    "(local llama-cpp). Use 'Qwen3-Coder-30B-A3B-Instruct-UD-Q4_K_XL.gguf__thinking' "
                    "to enable extended thinking for complex multi-step reasoning tasks."
                ),
            },
            "auth_type": {
                "type": "string",
                "description": "Override auth type. Defaults to 'openai' (local llama-cpp).",
            },
            "allowed_tools": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Restrict Qwen Code to only these tools (e.g. ['read_file', 'write_file']).",
            },
            "exclude_tools": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Prevent Qwen Code from using these tools.",
            },
            "timeout": {
                "type": "integer",
                "description": "Maximum seconds to wait for completion. Default: 900 (15 min). Increase for large refactors or test suites.",
                "default": 900,
            },
        },
        "required": ["prompt"],
    },
}

QWEN_TASK_ASYNC_SCHEMA = {
    "name": "qwen_task_async",
    "description": (
        "Start a Qwen Code task in the background and return immediately. "
        "Hermes will be automatically notified with the full result when Qwen Code finishes, "
        "at which point Hermes should assess the output and decide on next steps.\n\n"
        "Use this for tasks that may take a long time (e.g. large refactors, running test suites, "
        "multi-file changes). While Qwen Code is running, Hermes can continue other work.\n\n"
        "Returns a task_id to track progress with qwen_task_status."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "The task or question to send to Qwen Code. Be specific and complete.",
            },
            "working_dir": {
                "type": "string",
                "description": "Absolute path to the directory Qwen Code should operate in.",
            },
            "approval_mode": {
                "type": "string",
                "enum": ["yolo", "auto-edit", "default", "plan"],
                "description": "Permission mode for Qwen Code tool use. Default: yolo.",
                "default": "yolo",
            },
            "system_prompt": {
                "type": "string",
                "description": "Optional system prompt override for this Qwen Code session.",
            },
            "append_system_prompt": {
                "type": "string",
                "description": "Additional instructions appended to Qwen Code's default system prompt.",
            },
            "session_id": {
                "type": "string",
                "description": "Resume a previous Qwen Code session by its session ID.",
            },
            "model": {
                "type": "string",
                "description": (
                    "Override the model. Defaults to Qwen3-Coder-30B-A3B-Instruct-UD-Q4_K_XL.gguf "
                    "(local llama-cpp). Use 'Qwen3-Coder-30B-A3B-Instruct-UD-Q4_K_XL.gguf__thinking' "
                    "to enable extended thinking for complex multi-step reasoning tasks."
                ),
            },
            "auth_type": {
                "type": "string",
                "description": "Override auth type. Defaults to 'openai' (local llama-cpp).",
            },
            "allowed_tools": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Restrict Qwen Code to only these tools.",
            },
            "exclude_tools": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Prevent Qwen Code from using these tools.",
            },
            "timeout": {
                "type": "integer",
                "description": "Maximum seconds to wait before timing out. Default: 1800 (30 min).",
                "default": 1800,
            },
        },
        "required": ["prompt"],
    },
}

QWEN_TASK_STATUS_SCHEMA = {
    "name": "qwen_task_status",
    "description": (
        "Check the status of a specific Qwen Code task, or list all tasks in this session. "
        "Status values: running | completed | failed | timeout."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "task_id": {
                "type": "string",
                "description": (
                    "The task ID to check. Omit to list all tasks in the current session."
                ),
            },
        },
        "required": [],
    },
}

QWEN_TASK_RESULT_SCHEMA = {
    "name": "qwen_task_result",
    "description": (
        "Retrieve the full output of a completed Qwen Code task. "
        "Use this to re-read results that were already injected, or to access a specific task's output."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "task_id": {
                "type": "string",
                "description": "The task ID whose result to retrieve.",
            },
        },
        "required": ["task_id"],
    },
}

QWEN_SESSIONS_SCHEMA = {
    "name": "qwen_sessions",
    "description": (
        "List all Qwen Code tasks and sessions from the current Hermes session. "
        "Shows task IDs, statuses, session IDs (for continuation), and prompt previews."
    ),
    "parameters": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}

QWEN_CHECK_SCHEMA = {
    "name": "qwen_check",
    "description": (
        "Check whether Qwen Code is installed, where the binary is located, "
        "and whether authentication is configured. "
        "Run this first if you are unsure whether Qwen Code is available."
    ),
    "parameters": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}


# ---------------------------------------------------------------------------
# Interactive session schemas
# ---------------------------------------------------------------------------

QWEN_SESSION_START_SCHEMA = {
    "name": "qwen_session_start",
    "description": (
        "Start an interactive Qwen Code session in a PTY terminal. "
        "Unlike qwen_task (which runs a single prompt to completion), this opens "
        "a persistent interactive session where Hermes can have a back-and-forth "
        "conversation with Qwen Code — just like a human sitting at the terminal.\n\n"
        "Use this for:\n"
        "- Large projects that require iterative guidance and course-correction\n"
        "- Multi-step workflows where later steps depend on reviewing earlier results\n"
        "- Exploratory work where the full scope isn't known upfront\n"
        "- Sessions where Hermes needs to observe, assess, and steer Qwen's work\n\n"
        "After starting, use qwen_session_send to type messages and read Qwen's responses. "
        "The session stays open until explicitly stopped with qwen_session_stop."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "working_dir": {
                "type": "string",
                "description": (
                    "Absolute path to the directory Qwen Code should operate in. Required."
                ),
            },
            "model": {
                "type": "string",
                "description": (
                    "Override the model. Defaults to Qwen3-Coder-30B-A3B-Instruct-UD-Q4_K_XL.gguf."
                ),
            },
            "auth_type": {
                "type": "string",
                "description": "Override auth type. Defaults to 'openai' (local llama-cpp).",
            },
            "approval_mode": {
                "type": "string",
                "enum": ["yolo", "auto-edit", "default", "plan"],
                "description": "Permission mode for Qwen Code tool use. Default: yolo.",
                "default": "yolo",
            },
            "ready_timeout": {
                "type": "number",
                "description": (
                    "Seconds to wait for Qwen to show its ready prompt after starting. "
                    "Default: 30. Increase if model loading is slow."
                ),
                "default": 30,
            },
        },
        "required": ["working_dir"],
    },
}

QWEN_SESSION_SEND_SCHEMA = {
    "name": "qwen_session_send",
    "description": (
        "Type a message into an active interactive Qwen Code session and return immediately. "
        "Characters are sent one at a time (avoiding paste detection), then a background "
        "watcher monitors for output to stabilize. When Qwen finishes responding, "
        "Hermes is automatically notified via inject_message — exactly like qwen_task_async.\n\n"
        "This call does NOT block. After calling this, do NOT poll or call anything else — "
        "just wait for the automatic notification. When it arrives, read Qwen's output, "
        "assess it, and decide the next step:\n"
        "- Send another message to continue/correct the work\n"
        "- Stop the session if work is complete (use qwen_session_stop)\n"
        "- Use qwen_session_wait to check on progress before the notification arrives"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "session_id": {
                "type": "string",
                "description": "The session ID returned by qwen_session_start.",
            },
            "message": {
                "type": "string",
                "description": (
                    "The message to type into the Qwen Code terminal. "
                    "Be specific and clear — this is typed as if a human were at the keyboard."
                ),
            },
            "idle_timeout": {
                "type": "number",
                "description": (
                    "Seconds of no new output before considering Qwen 'done responding'. "
                    "Default: 3.0. Increase for tasks that involve long compilations or test runs."
                ),
                "default": 3.0,
            },
            "max_wait": {
                "type": "number",
                "description": (
                    "Maximum seconds to wait for output to stabilize. Default: 300 (5 min). "
                    "If reached, returns whatever output is available."
                ),
                "default": 300,
            },
        },
        "required": ["session_id", "message"],
    },
}

QWEN_SESSION_READ_SCHEMA = {
    "name": "qwen_session_read",
    "description": (
        "Read output from an interactive Qwen Code session without sending a message. "
        "Use this to check what Qwen has produced since the last read, or to get "
        "the full session transcript.\n\n"
        "This is useful when:\n"
        "- Qwen is still producing output from a previous message\n"
        "- You want to review the full session history\n"
        "- You want to check if Qwen has finished a long-running operation"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "session_id": {
                "type": "string",
                "description": "The session ID to read from.",
            },
            "full": {
                "type": "boolean",
                "description": (
                    "If true, return ALL output since session start. "
                    "If false (default), return only new output since the last read."
                ),
                "default": False,
            },
        },
        "required": ["session_id"],
    },
}

QWEN_SESSION_WAIT_SCHEMA = {
    "name": "qwen_session_wait",
    "description": (
        "Wait for an interactive Qwen Code session's output to stabilize. "
        "Blocks until no new output has been produced for idle_timeout seconds, "
        "or until max_wait is reached. Returns the new output.\n\n"
        "Use this when Qwen is in the middle of a long operation (running tests, "
        "building, installing dependencies) and you want to wait for it to finish "
        "before deciding what to do next."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "session_id": {
                "type": "string",
                "description": "The session ID to wait on.",
            },
            "idle_timeout": {
                "type": "number",
                "description": (
                    "Seconds of stable (no new) output before returning. Default: 3.0."
                ),
                "default": 3.0,
            },
            "max_wait": {
                "type": "number",
                "description": (
                    "Maximum seconds to block waiting. Default: 30s — safe for the agent thread. "
                    "If Qwen is still running at max_wait, returns timed_out=true with partial output. "
                    "The background watcher from qwen_session_send will still notify Hermes when done."
                ),
                "default": 30,
            },
        },
        "required": ["session_id"],
    },
}

QWEN_SESSION_STOP_SCHEMA = {
    "name": "qwen_session_stop",
    "description": (
        "Close an interactive Qwen Code session. Sends Ctrl+C and terminates the process. "
        "Returns a summary of the session duration and total output length.\n\n"
        "Always stop sessions when work is complete to free resources."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "session_id": {
                "type": "string",
                "description": "The session ID to stop.",
            },
        },
        "required": ["session_id"],
    },
}

QWEN_SESSION_LIST_SCHEMA = {
    "name": "qwen_session_list",
    "description": (
        "List all interactive Qwen Code sessions (active and closed). "
        "Shows session IDs, statuses, working directories, and durations."
    ),
    "parameters": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}
