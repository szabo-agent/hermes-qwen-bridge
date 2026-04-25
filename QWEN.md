# Hermes Qwen Bridge — Improvement Plan

## Project Summary

A Python plugin for the Hermes Agent framework that bridges to `Qwen Code` (the agentic coding CLI). Similar in architecture to the hermes-pi-bridge but targets Qwen Code's PTY-based interactive mode. Features: sync/async task delegation, PTY interactive sessions with character-by-character typing to avoid paste detection, idle-watcher based response detection, coding-request auto-detection via regex, and skill documents for Hermes guidance. Pure stdlib Python.

**Tech stack:** Python 3.10+, Hermes Agent plugin framework, pty/os/select/termios for PTY management, subprocess for Qwen Code execution.

---

## Quality-of-Life Improvements

### Phase 1: Reliability & Robustness

**1. PTY Signal Handling Race Conditions**
`stop_session()` sends SIGINT twice, types `exit`, then SIGKILLS. There's a window where the child process could receive signals while the reader thread is blocking on `select()`. Add proper signal handling with `sigaction` or at minimum a timeout-based unblock of the select call.

**2. Qwen Code Version Compatibility Matrix**
The parser handles both snake_case and camelCase for fields (Qwen Code 0.14+ vs older). Add explicit version detection in `qwen_check` that maps detected versions to known field layouts, making failures actionable rather than falling back to defaults.

**3. PTY Resize Handling**
Terminal size is set via `TIOCSWINSZ` on start but never updated if the Hermes window resizes. For very wide prompts, this causes line-wrapping in Qwen Code's output which corrupts the text buffer. Add a resize handler that forwards the current terminal dimensions.

**4. Message Fragmentation at Character Boundaries**
Character-by-character typing (0.005s delay) is slow for long messages. For prompts >1000 chars, the idle watcher may fire before all characters are typed if Qwen Code responds to early characters. Add a "typing done" signal (e.g., check if stdin buffer is empty) before starting the idle watcher.

### Phase 2: Feature Expansion

**5. Session Export / Sharing**
Export an interactive session's full transcript (prompts + responses with timestamps) as markdown or JSON. Useful for sharing debugging sessions, documenting solutions, or building training data. Add `qwen_session_export <sessionId> --format json|md`.

**6. Qwen Code Tool Call Monitoring**
Currently the plugin only captures text output. Qwen Code makes real tool calls (file edits, shell commands) visible in its JSON stream. Parse and surface these as structured events in Hermes: "Qwen is reading file...", "Qwen ran `npm install express`", "Qwen edited 3 files". This gives Hermes visibility into the sub-agent's actual work.

**7. Adaptive Idle Timeout**
Current idle timeout is a fixed default (3s). Make it adaptive: measure average response time per prompt across the session and adjust the timeout accordingly. Complex coding tasks get longer timeouts; simple formatting gets shorter ones.

**8. Prompt Queuing for Sessions**
Currently `pi_session_send` sends one prompt at a time and waits for the idle watcher. Add a prompt queue so users can batch multiple prompts: "implement login form", then "add validation", then "write tests". Each gets processed sequentially with proper spacing.

### Phase 3: Integration & UX

**9. File Diff Output in Results**
When Qwen Code edits files, capture the diff (using `git diff` if the sandbox has git initialized) and include it in the injected message to Hermes. Makes it easier for Hermes to review what changed without re-reading entire files.

**10. Skill Document Generation from Usage Patterns**
The SKILL.md and SKILL_SESSION.md are hand-written. Over time, as users interact with the bridge, auto-generate updated skill documents that reflect common usage patterns, recommended thinking levels per task type, and success/failure rates. Keeps documentation in sync with actual behavior.

---

## Priority Order

| # | Feature | Effort | Impact | Rationale |
|---|---------|--------|--------|-----------|
| 1 | PTY signal handling race conditions | Low-Medium | Critical | Prevents process leaks and hangs |
| 2 | Qwen Code version compatibility matrix | Low | High | Makes failures actionable |
| 3 | Tool call monitoring/surface | Medium | High | Gives Hermes real visibility into sub-agent work |
| 4 | File diff output | Low-Medium | Medium | Better reviewability of changes |
| 5 | Adaptive idle timeout | Low | Medium | Reduces latency for simple tasks |
| 6 | Session export/sharing | Medium | Medium | Debugging and documentation |
| 7 | Prompt queuing | Low-Medium | Medium | Multi-step workflows in sessions |
