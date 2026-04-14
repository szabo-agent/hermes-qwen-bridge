"""
Interactive terminal session manager for Qwen Code.

Spawns Qwen in interactive mode via a PTY and drives it the way a human
would: typing characters one at a time, waiting for output to settle,
then reading what appeared on screen.

Uses only stdlib modules (pty, os, select, subprocess) — no external deps.
"""

from __future__ import annotations

import errno
import fcntl
import logging
import os
import pty
import re
import select
import shutil
import signal
import struct
import subprocess
import termios
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ANSI escape stripping
# ---------------------------------------------------------------------------

_ANSI_RE = re.compile(r"""
    \x1b          # ESC
    (?:
        \[[\d;]*[A-Za-z]   # CSI sequences  (e.g. \x1b[31m, \x1b[2J)
      | \].*?\x07          # OSC sequences  (e.g. \x1b]0;title\x07)
      | \][^\x07]*\x1b\\   # OSC with ST    (e.g. \x1b]0;title\x1b\\)
      | [()][AB012]        # charset select
      | [=>]               # keypad modes
      | [\x20-\x2f][\x30-\x7e]  # 2-byte sequences
    )
""", re.VERBOSE)

# Also strip common control chars that leak through
_CTRL_RE = re.compile(r'[\x00-\x08\x0e-\x1f\x7f]')


def strip_ansi(text: str) -> str:
    """Remove ANSI escape codes and control characters from terminal output."""
    text = _ANSI_RE.sub("", text)
    text = _CTRL_RE.sub("", text)
    return text


def _set_pty_size(fd: int, rows: int, cols: int) -> None:
    """Set the terminal size on a PTY file descriptor."""
    winsize = struct.pack("HHHH", rows, cols, 0, 0)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)


# ---------------------------------------------------------------------------
# Interactive session dataclass
# ---------------------------------------------------------------------------

@dataclass
class QwenInteractiveSession:
    session_id: str
    working_dir: str
    status: str = "starting"   # starting | ready | busy | closed | error
    created_at: float = field(default_factory=time.time)

    # PTY file descriptors and child PID
    _master_fd: int = field(default=-1, repr=False)
    _child_pid: int = field(default=-1, repr=False)

    # Accumulated raw output and reader state
    _output_buffer: str = field(default="", repr=False)
    _last_output_time: float = field(default=0.0, repr=False)
    _last_read_pos: int = field(default=0, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _reader_thread: Optional[threading.Thread] = field(default=None, repr=False)
    _stop_reader: bool = field(default=False, repr=False)

    # Error detail if status == "error"
    error: Optional[str] = None

    @property
    def is_alive(self) -> bool:
        """Check if the child process is still running."""
        if self._child_pid <= 0:
            return False
        try:
            pid, status = os.waitpid(self._child_pid, os.WNOHANG)
            if pid == 0:
                return True   # still running
            return False      # exited
        except ChildProcessError:
            return False

    def new_output(self) -> str:
        """Return output accumulated since the last call to new_output()."""
        with self._lock:
            new = self._output_buffer[self._last_read_pos:]
            self._last_read_pos = len(self._output_buffer)
        return strip_ansi(new)

    def all_output(self) -> str:
        """Return all accumulated output (cleaned)."""
        with self._lock:
            raw = self._output_buffer
        return strip_ansi(raw)

    def time_since_last_output(self) -> float:
        """Seconds since the last byte was received from the PTY."""
        with self._lock:
            if self._last_output_time == 0:
                return 0.0
            return time.time() - self._last_output_time


# ---------------------------------------------------------------------------
# Session store
# ---------------------------------------------------------------------------

_sessions: Dict[str, QwenInteractiveSession] = {}


def get_session(session_id: str) -> Optional[QwenInteractiveSession]:
    return _sessions.get(session_id)


def list_sessions() -> List[QwenInteractiveSession]:
    return sorted(_sessions.values(), key=lambda s: s.created_at, reverse=True)


def active_session_count() -> int:
    return sum(1 for s in _sessions.values() if s.status in ("starting", "ready", "busy"))


# ---------------------------------------------------------------------------
# Background reader thread
# ---------------------------------------------------------------------------

def _reader_loop(session: QwenInteractiveSession) -> None:
    """Continuously read from the PTY master fd and accumulate output."""
    master_fd = session._master_fd
    while not session._stop_reader:
        try:
            # Use select with a short timeout so we can check _stop_reader
            ready, _, _ = select.select([master_fd], [], [], 0.5)
            if not ready:
                # Check if process is still alive during quiet periods
                if not session.is_alive:
                    break
                continue
            chunk = os.read(master_fd, 4096)
            if not chunk:
                # EOF — process closed its side
                break
            text = chunk.decode("utf-8", errors="replace")
            with session._lock:
                session._output_buffer += text
                session._last_output_time = time.time()
        except OSError as exc:
            if exc.errno == errno.EIO:
                # EIO means the child closed the PTY — normal on exit
                break
            if exc.errno == errno.EBADF:
                break
            logger.warning("qwen-interactive: reader OS error for %s: %s", session.session_id, exc)
            break
        except Exception as exc:
            logger.warning("qwen-interactive: reader error for %s: %s", session.session_id, exc)
            break

    # Mark closed if the process died
    if not session.is_alive and session.status != "closed":
        session.status = "closed"
        logger.info("qwen-interactive: session %s process exited", session.session_id)


# ---------------------------------------------------------------------------
# Session lifecycle
# ---------------------------------------------------------------------------

def start_session(
    working_dir: str,
    model: Optional[str] = None,
    auth_type: Optional[str] = None,
    approval_mode: str = "yolo",
    extra_args: Optional[List[str]] = None,
    ready_timeout: float = 30.0,
    cols: int = 160,
    rows: int = 50,
) -> QwenInteractiveSession:
    """
    Start Qwen Code in interactive mode inside a PTY.

    Blocks until the ready prompt appears or ready_timeout is reached.
    """
    session_id = str(uuid.uuid4())[:8]
    session = QwenInteractiveSession(
        session_id=session_id,
        working_dir=working_dir,
    )

    # Find the qwen binary
    qwen_bin = shutil.which("qwen")
    if not qwen_bin:
        candidates = [
            os.path.expanduser("~/.local/bin/qwen"),
            os.path.expanduser("~/.npm-global/bin/qwen"),
            "/usr/local/bin/qwen",
        ]
        for c in candidates:
            if os.path.isfile(c):
                qwen_bin = c
                break

    if not qwen_bin:
        session.status = "error"
        session.error = "Qwen Code binary not found. Install with: npm install -g @qwen-code/qwen-code"
        _sessions[session_id] = session
        return session

    # Build command — interactive mode (no -p flag)
    cmd_parts = [qwen_bin]
    cmd_parts += ["--approval-mode", approval_mode]

    if model:
        cmd_parts += ["--model", model]
    else:
        from .tools import DEFAULT_MODEL
        cmd_parts += ["--model", DEFAULT_MODEL]

    if auth_type:
        cmd_parts += ["--auth-type", auth_type]
    else:
        from .tools import DEFAULT_AUTH_TYPE
        cmd_parts += ["--auth-type", DEFAULT_AUTH_TYPE]

    if extra_args:
        cmd_parts += extra_args

    cmd_str = " ".join(cmd_parts)
    logger.info("qwen-interactive: starting session %s in %s — %s", session_id, working_dir, cmd_str)

    try:
        # Create a PTY pair
        master_fd, slave_fd = pty.openpty()

        # Set terminal size
        _set_pty_size(master_fd, rows, cols)

        # Set slave to raw mode to avoid local echo issues
        attrs = termios.tcgetattr(slave_fd)
        attrs[3] &= ~termios.ECHO   # Disable echo on slave
        termios.tcsetattr(slave_fd, termios.TCSANOW, attrs)

        # Spawn the child process
        env = {**os.environ, "TERM": "xterm-256color"}
        child_pid = os.fork()

        if child_pid == 0:
            # Child process
            os.close(master_fd)
            os.setsid()

            # Make the slave fd the controlling terminal
            fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)

            # Redirect stdin/stdout/stderr to the slave PTY
            os.dup2(slave_fd, 0)
            os.dup2(slave_fd, 1)
            os.dup2(slave_fd, 2)
            if slave_fd > 2:
                os.close(slave_fd)

            os.chdir(working_dir)
            os.execvpe(cmd_parts[0], cmd_parts, env)
            # execvpe does not return; if it fails, the child exits
        else:
            # Parent process
            os.close(slave_fd)
            session._master_fd = master_fd
            session._child_pid = child_pid

    except Exception as exc:
        session.status = "error"
        session.error = f"Failed to spawn Qwen: {type(exc).__name__}: {exc}"
        _sessions[session_id] = session
        return session

    # Start the background reader
    session._reader_thread = threading.Thread(
        target=_reader_loop,
        args=(session,),
        daemon=True,
        name=f"qwen-reader-{session_id}",
    )
    session._reader_thread.start()

    # Wait for the ready prompt
    deadline = time.time() + ready_timeout
    ready = False
    while time.time() < deadline:
        with session._lock:
            buf = session._output_buffer.lower()
        if "type your message" in buf or "what can i help" in buf:
            ready = True
            break
        if not session.is_alive:
            break
        time.sleep(0.3)

    if ready:
        session.status = "ready"
        logger.info("qwen-interactive: session %s is ready", session_id)
    elif not session.is_alive:
        session.status = "error"
        output = strip_ansi(session._output_buffer)
        session.error = f"Qwen process exited during startup. Output:\n{output[-500:]}"
    else:
        # Timed out but process is still alive — might just be slow
        session.status = "ready"
        logger.warning(
            "qwen-interactive: session %s did not show ready prompt within %.0fs, "
            "but process is alive — marking ready anyway",
            session_id, ready_timeout,
        )

    _sessions[session_id] = session
    return session


def _clean_output(raw: str, sent_message: str) -> str:
    """Strip ANSI codes and remove the echoed input line from Qwen's response."""
    text = strip_ansi(raw)
    lines = text.split("\n")
    cleaned = []
    stripped = False
    for line in lines:
        if not stripped and sent_message.strip() and sent_message.strip() in line.strip():
            stripped = True
            continue
        cleaned.append(line)
    return "\n".join(cleaned).strip()


def _idle_watcher(
    session: QwenInteractiveSession,
    sent_message: str,
    idle_timeout: float,
    max_wait: float,
    send_pos: int,
) -> None:
    """
    Background thread: waits for Qwen's output to stabilize after a message was sent,
    then injects the response into Hermes via inject_message.
    """
    from .tools import _ctx_ref

    deadline = time.time() + max_wait
    # Give Qwen a moment to start producing output
    time.sleep(0.5)

    while time.time() < deadline:
        if not session.is_alive:
            break
        idle_time = session.time_since_last_output()
        if idle_time >= idle_timeout and session._last_output_time > 0:
            break
        time.sleep(0.3)

    # Collect output since the send
    with session._lock:
        raw_new = session._output_buffer[send_pos:]
        session._last_read_pos = len(session._output_buffer)

    output = _clean_output(raw_new, sent_message)
    timed_out = time.time() >= deadline

    if session.is_alive:
        session.status = "ready"
    else:
        session.status = "closed"

    logger.debug(
        "qwen-interactive: session %s idle after %.1fs (timed_out=%s), %d chars of output",
        session.session_id, session.time_since_last_output(), timed_out, len(output),
    )

    if _ctx_ref:
        if timed_out:
            note = (
                f"[qwen-interactive] Session `{session.session_id}` is still producing output "
                f"after {max_wait:.0f}s. Partial output below. Use qwen_session_wait to collect "
                f"more, or qwen_session_read to check status.\n\n"
            )
        else:
            note = f"[qwen-interactive] Session `{session.session_id}` response ready.\n\n"

        inject = (
            f"{note}"
            f"**Qwen output:**\n{output or '(no new output)'}\n\n"
            f"Review Qwen's output above. Decide whether to:\n"
            f"- Send the next instruction: qwen_session_send(session_id=\"{session.session_id}\", message=\"...\")\n"
            f"- Read more output: qwen_session_read(session_id=\"{session.session_id}\")\n"
            f"- Stop: qwen_session_stop(session_id=\"{session.session_id}\")"
        )
        _ctx_ref.inject_message(inject, role="user")
    else:
        # No context ref — fall back to storing on session for manual retrieval
        logger.warning(
            "qwen-interactive: no ctx_ref available for session %s, output not injected",
            session.session_id,
        )


def send_message(
    session_id: str,
    message: str,
    char_delay: float = 0.005,
    idle_timeout: float = 3.0,
    max_wait: float = 300.0,
) -> dict:
    """
    Type a message into the interactive Qwen session and return immediately.

    Characters are sent one at a time (avoids paste detection), then a background
    watcher thread monitors for output to stabilize. When Qwen goes idle,
    Hermes is automatically notified via inject_message — the same mechanism
    used by qwen_task_async.

    This call does NOT block waiting for Qwen's response. Hermes will receive
    a notification message when Qwen finishes.

    Args:
        session_id: The session to send to.
        message: The text to type.
        char_delay: Seconds between each keystroke (avoids paste detection).
        idle_timeout: Seconds of no new output before considering Qwen "done".
        max_wait: Maximum seconds to wait before sending partial output anyway.
    """
    session = _sessions.get(session_id)
    if not session:
        return {"error": f"Session {session_id!r} not found"}
    if session.status == "closed":
        return {"error": f"Session {session_id!r} is closed"}
    if session.status == "error":
        return {"error": f"Session {session_id!r} is in error state: {session.error}"}
    if not session.is_alive:
        session.status = "closed"
        return {"error": f"Session {session_id!r} process has exited"}

    master_fd = session._master_fd

    # Record buffer position before sending so the watcher can slice new output
    with session._lock:
        send_pos = len(session._output_buffer)
        session._last_read_pos = send_pos

    session.status = "busy"

    # Type the message character by character
    try:
        for ch in message:
            os.write(master_fd, ch.encode("utf-8"))
            time.sleep(char_delay)
        os.write(master_fd, b"\r")
    except OSError as exc:
        session.status = "error"
        session.error = f"Write error: {exc}"
        return {"error": f"Failed to send to session: {exc}"}

    # Start background watcher — it will inject_message when Qwen goes idle
    watcher = threading.Thread(
        target=_idle_watcher,
        args=(session, message, idle_timeout, max_wait, send_pos),
        daemon=True,
        name=f"qwen-watcher-{session.session_id}",
    )
    watcher.start()
    logger.debug(
        "qwen-interactive: sent message to session %s, watcher started (idle=%.1fs, max=%.0fs)",
        session_id, idle_timeout, max_wait,
    )

    return {
        "status": "responding",
        "session_id": session_id,
        "message": (
            f"Message sent to Qwen session `{session_id}`. "
            f"Hermes will be automatically notified when Qwen finishes responding "
            f"(idle for {idle_timeout}s, max wait {max_wait:.0f}s). "
            f"Do NOT poll — wait for the notification, then assess Qwen's output and decide next steps."
        ),
    }


def read_output(session_id: str, full: bool = False) -> dict:
    """
    Read output from the session without sending anything.

    Args:
        session_id: The session to read from.
        full: If True, return all output since session start. Otherwise, only new output.
    """
    session = _sessions.get(session_id)
    if not session:
        return {"error": f"Session {session_id!r} not found"}

    if full:
        output = session.all_output()
    else:
        output = session.new_output()

    return {
        "status": session.status,
        "output": output,
        "idle_seconds": round(session.time_since_last_output(), 1),
        "process_alive": session.is_alive,
    }


def wait_for_idle(
    session_id: str,
    idle_timeout: float = 3.0,
    max_wait: float = 30.0,
) -> dict:
    """
    Poll for output stability for up to max_wait seconds, then return.

    Default max_wait is 30s — safe to call from the Hermes agent thread.
    If Qwen is still running when max_wait is reached, returns timed_out=True
    with whatever output has arrived so far. The background watcher started
    by qwen_session_send will still inject the full response when Qwen finishes.

    Use this when you want to check on progress without waiting for the full
    inject_message notification.
    """
    session = _sessions.get(session_id)
    if not session:
        return {"error": f"Session {session_id!r} not found"}

    deadline = time.time() + max_wait
    while time.time() < deadline:
        if not session.is_alive:
            break
        idle_time = session.time_since_last_output()
        if idle_time >= idle_timeout and session._last_output_time > 0:
            break
        time.sleep(0.3)

    new_output = session.new_output()
    timed_out = time.time() >= deadline

    return {
        "status": session.status,
        "output": new_output,
        "idle_seconds": round(session.time_since_last_output(), 1),
        "process_alive": session.is_alive,
        "timed_out": timed_out,
        "note": (
            "Qwen is still responding. The background watcher will notify Hermes automatically."
            if timed_out else "Qwen has finished responding."
        ),
    }


def stop_session(session_id: str) -> dict:
    """Close an interactive session."""
    session = _sessions.get(session_id)
    if not session:
        return {"error": f"Session {session_id!r} not found"}

    session._stop_reader = True

    if session._child_pid > 0 and session.is_alive:
        try:
            # Send Ctrl+C (SIGINT) first
            os.kill(session._child_pid, signal.SIGINT)
            time.sleep(0.5)
            if session.is_alive:
                os.kill(session._child_pid, signal.SIGINT)
                time.sleep(0.5)
            if session.is_alive:
                # Try typing 'exit\r'
                try:
                    os.write(session._master_fd, b"exit\r")
                except OSError:
                    pass
                time.sleep(1.0)
            if session.is_alive:
                # Force kill
                os.kill(session._child_pid, signal.SIGKILL)
                time.sleep(0.3)
        except ProcessLookupError:
            pass  # already exited
        except Exception as exc:
            logger.warning("qwen-interactive: error stopping session %s: %s", session_id, exc)

    # Reap the child process to avoid zombies
    if session._child_pid > 0:
        try:
            os.waitpid(session._child_pid, os.WNOHANG)
        except ChildProcessError:
            pass

    # Close the master fd
    if session._master_fd >= 0:
        try:
            os.close(session._master_fd)
        except OSError:
            pass
        session._master_fd = -1

    # Wait for reader thread to finish
    if session._reader_thread and session._reader_thread.is_alive():
        session._reader_thread.join(timeout=3.0)

    session.status = "closed"
    final_output = session.all_output()
    duration = time.time() - session.created_at

    return {
        "status": "closed",
        "session_id": session_id,
        "duration_seconds": round(duration, 1),
        "total_output_length": len(final_output),
    }
