"""Start, reuse, inspect, and stop the background proxy used by ``codefa <client>``.

The auto-started server is detached from the launching terminal so that it
survives the client exiting and can be shared by concurrent client sessions.
Its console output is captured to a log file so startup failures are explained
instead of silently discarded.
"""

import os
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from codefa.cli.launchers.common import preflight_proxy
from codefa.config.paths import (
    background_server_console_path,
    background_server_pid_path,
)

SERVER_START_TIMEOUT_SECONDS = 45.0
SERVER_STOP_TIMEOUT_SECONDS = 10.0
_POLL_INTERVAL_SECONDS = 0.2
_LOG_TAIL_LINES = 25
_SERVER_COMMAND = ("-c", "from codefa.cli.entrypoints import serve; serve()")


class BackgroundServerError(RuntimeError):
    """The background server could not be started."""


@dataclass(frozen=True, slots=True)
class BackgroundServerStatus:
    reachable: bool
    pid: int | None
    pid_alive: bool


def ensure_background_server(
    proxy_root_url: str,
    *,
    admin_url: str,
    timeout: float = SERVER_START_TIMEOUT_SECONDS,
    probe: Callable[[str], str | None] = preflight_proxy,
) -> bool:
    """Reuse a reachable proxy or start a detached one; return True when started."""
    if probe(proxy_root_url) is None:
        return False

    console_path = background_server_console_path()
    console_path.parent.mkdir(parents=True, exist_ok=True)
    print("Starting codefa server in the background...", flush=True)
    with console_path.open("wb") as console:
        process = subprocess.Popen(
            [sys.executable, *_SERVER_COMMAND],
            stdin=subprocess.DEVNULL,
            stdout=console,
            stderr=subprocess.STDOUT,
            env=background_server_env(os.environ),
            **_detached_process_kwargs(),
        )
    _write_pid(process.pid)

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if probe(proxy_root_url) is None:
            print(f"codefa server ready · admin UI: {admin_url}", flush=True)
            return True
        return_code = process.poll()
        if return_code is not None:
            _remove_pid_file()
            raise BackgroundServerError(
                f"codefa server exited during startup (exit code {return_code})."
                f"{_console_tail(console_path)}"
            )
        time.sleep(_POLL_INTERVAL_SECONDS)

    _terminate(process.pid)
    _remove_pid_file()
    raise BackgroundServerError(
        f"codefa server did not become ready within {timeout:g}s."
        f"{_console_tail(console_path)}"
    )


def background_server_env(base_env: Mapping[str, str]) -> dict[str, str]:
    """Return the background server environment (no browser pop-ups, unbuffered)."""
    env = dict(base_env)
    env["CODEFA_OPEN_BROWSER"] = "false"
    env["PYTHONUNBUFFERED"] = "1"
    return env


def background_server_status(
    proxy_root_url: str,
    *,
    probe: Callable[[str], str | None] = preflight_proxy,
) -> BackgroundServerStatus:
    pid = _read_pid()
    return BackgroundServerStatus(
        reachable=probe(proxy_root_url) is None,
        pid=pid,
        pid_alive=pid is not None and _is_codefa_process(pid),
    )


def stop_background_server(timeout: float = SERVER_STOP_TIMEOUT_SECONDS) -> str:
    """Stop the auto-started server and return a user-facing result."""
    pid = _read_pid()
    if pid is None:
        return "No background codefa server is running."
    if not _is_codefa_process(pid):
        _remove_pid_file()
        return "No background codefa server is running (removed stale pid file)."

    _terminate(pid)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and _pid_alive(pid):
        time.sleep(_POLL_INTERVAL_SECONDS)
    if _pid_alive(pid) and os.name != "nt":
        os.kill(pid, signal.SIGKILL)
    _remove_pid_file()
    return f"Stopped background codefa server (pid {pid})."


def _detached_process_kwargs() -> dict[str, Any]:
    if os.name == "nt":
        flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(
            subprocess, "DETACHED_PROCESS", 0
        )
        return {"creationflags": flags}
    # A new session keeps terminal signals (Ctrl+C, hangup) away from the server.
    return {"start_new_session": True}


def _console_tail(path: Path) -> str:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    tail = [line for line in lines[-_LOG_TAIL_LINES:] if line.strip()]
    if not tail:
        return f"\nNo server output was captured. Log file: {path}"
    return f"\nLast server output ({path}):\n" + "\n".join(f"  {line}" for line in tail)


def _write_pid(pid: int) -> None:
    path = background_server_pid_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{pid}\n", encoding="utf-8")


def _read_pid() -> int | None:
    try:
        raw = background_server_pid_path().read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return int(raw) if raw.isdigit() and int(raw) > 0 else None


def _remove_pid_file() -> None:
    background_server_pid_path().unlink(missing_ok=True)


def _pid_alive(pid: int) -> bool:
    if os.name == "nt":
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True,
            text=True,
            check=False,
        )
        return str(pid) in result.stdout
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _is_codefa_process(pid: int) -> bool:
    """Guard against signalling an unrelated process that reused the pid."""
    if not _pid_alive(pid):
        return False
    if os.name == "nt":
        return True
    result = subprocess.run(
        ["ps", "-p", str(pid), "-o", "command="],
        capture_output=True,
        text=True,
        check=False,
    )
    return "codefa" in result.stdout


def _terminate(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
