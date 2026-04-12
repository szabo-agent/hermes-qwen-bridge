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
