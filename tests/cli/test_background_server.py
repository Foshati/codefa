"""Tests for the auto-started background proxy used by ``codefa <client>``."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from codefa.cli import background_server
from codefa.cli.background_server import (
    BackgroundServerError,
    background_server_env,
    background_server_status,
    ensure_background_server,
    stop_background_server,
)
from codefa.cli.entrypoints import _parse_combined_args, _run_combined
from codefa.config.paths import (
    background_server_console_path,
    background_server_pid_path,
)

_URL = "http://127.0.0.1:8090"
_ADMIN = "http://127.0.0.1:8090/admin"


@pytest.fixture(autouse=True)
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(background_server, "_POLL_INTERVAL_SECONDS", 0.0)
    return tmp_path


def _probe(*results: str | None):
    """Return successive probe results, repeating the last one."""
    values = list(results)

    def probe(_url: str) -> str | None:
        return values.pop(0) if len(values) > 1 else values[0]

    return probe


def test_reachable_proxy_is_reused_without_spawning():
    with patch.object(background_server.subprocess, "Popen") as popen:
        assert (
            ensure_background_server(_URL, admin_url=_ADMIN, probe=_probe(None))
            is False
        )
    popen.assert_not_called()


def test_server_starts_detached_and_records_pid(capsys):
    process = MagicMock(pid=4242)
    process.poll.return_value = None
    with patch.object(
        background_server.subprocess, "Popen", return_value=process
    ) as popen:
        started = ensure_background_server(
            _URL, admin_url=_ADMIN, probe=_probe("refused", "refused", None)
        )

    assert started is True
    kwargs = popen.call_args.kwargs
    assert kwargs["env"]["CODEFA_OPEN_BROWSER"] == "false"
    assert kwargs["stdin"] is background_server.subprocess.DEVNULL
    assert kwargs.get("start_new_session") is True or "creationflags" in kwargs
    assert background_server_pid_path().read_text().strip() == "4242"
    assert _ADMIN in capsys.readouterr().out


def test_early_exit_reports_captured_server_output():
    process = MagicMock(pid=7)
    process.poll.return_value = 1

    def fake_popen(*_args, **kwargs):
        kwargs["stdout"].write(b"ERROR: [Errno 48] address already in use\n")
        return process

    with (
        patch.object(background_server.subprocess, "Popen", side_effect=fake_popen),
        pytest.raises(BackgroundServerError, match="address already in use") as excinfo,
    ):
        ensure_background_server(_URL, admin_url=_ADMIN, probe=_probe("refused"))

    assert "exit code 1" in str(excinfo.value)
    assert str(background_server_console_path()) in str(excinfo.value)
    assert not background_server_pid_path().exists()


def test_startup_timeout_terminates_server():
    process = MagicMock(pid=99)
    process.poll.return_value = None
    with (
        patch.object(background_server.subprocess, "Popen", return_value=process),
        patch.object(background_server, "_terminate") as terminate,
        pytest.raises(BackgroundServerError, match="did not become ready"),
    ):
        ensure_background_server(
            _URL, admin_url=_ADMIN, timeout=0.0, probe=_probe("refused")
        )
    terminate.assert_called_once_with(99)
    assert not background_server_pid_path().exists()


def test_background_env_preserves_caller_values():
    env = background_server_env({"PATH": "/bin", "CODEFA_OPEN_BROWSER": "true"})
    assert env == {
        "PATH": "/bin",
        "CODEFA_OPEN_BROWSER": "false",
        "PYTHONUNBUFFERED": "1",
    }


def test_stop_without_server():
    assert "No background codefa server" in stop_background_server()


def test_stop_removes_stale_pid_file():
    background_server_pid_path().parent.mkdir(parents=True, exist_ok=True)
    background_server_pid_path().write_text("123\n")
    with patch.object(background_server, "_is_codefa_process", return_value=False):
        assert "stale" in stop_background_server()
    assert not background_server_pid_path().exists()


def test_stop_terminates_recorded_server():
    background_server_pid_path().parent.mkdir(parents=True, exist_ok=True)
    background_server_pid_path().write_text("321\n")
    with (
        patch.object(background_server, "_is_codefa_process", return_value=True),
        patch.object(background_server, "_pid_alive", return_value=False),
        patch.object(background_server, "_terminate") as terminate,
    ):
        assert "Stopped" in stop_background_server()
    terminate.assert_called_once_with(321)
    assert not background_server_pid_path().exists()


def test_status_reports_reachability_and_pid():
    background_server_pid_path().parent.mkdir(parents=True, exist_ok=True)
    background_server_pid_path().write_text("55\n")
    with patch.object(background_server, "_is_codefa_process", return_value=True):
        status = background_server_status(_URL, probe=_probe(None))
    assert (status.reachable, status.pid, status.pid_alive) == (True, 55, True)


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["stop"], ("stop", [])),
        (["--status"], ("status", [])),
        (["claude", "stop"], ("claude", ["stop"])),
        (["claude", "--resume"], ("claude", ["--resume"])),
    ],
)
def test_parse_combined_args_management_commands(argv, expected):
    assert _parse_combined_args(argv) == expected


def test_combined_keeps_shared_server_running_after_client_exits(capsys):
    with (
        patch(
            "codefa.cli.background_server.ensure_background_server", return_value=True
        ),
        patch(
            "codefa.cli.launchers.claude.launch", side_effect=SystemExit(0)
        ) as launch,
        patch.object(background_server, "_terminate") as terminate,
        pytest.raises(SystemExit),
    ):
        _run_combined(["claude", "--resume"])

    launch.assert_called_once_with(["--resume"])
    terminate.assert_not_called()
    assert "codefa stop" in capsys.readouterr().err


def test_combined_reports_startup_failure(capsys):
    with (
        patch(
            "codefa.cli.background_server.ensure_background_server",
            side_effect=BackgroundServerError("boom details"),
        ),
        patch("codefa.cli.launchers.claude.launch") as launch,
        pytest.raises(SystemExit) as excinfo,
    ):
        _run_combined(["claude"])

    assert excinfo.value.code == 1
    launch.assert_not_called()
    assert "boom details" in capsys.readouterr().err
