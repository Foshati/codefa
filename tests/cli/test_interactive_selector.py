"""Tests for the interactive client selector and subcommand routing in ``codefa``."""

from unittest.mock import patch

from codefa.cli.entrypoints import (
    _parse_combined_args,
    _select_client_interactively,
    combined,
)


def test_parse_combined_args_empty():
    target, remaining = _parse_combined_args([])
    assert target is None
    assert remaining == []


def test_parse_combined_args_claude():
    target, remaining = _parse_combined_args(["claude", "--model", "opus"])
    assert target == "claude"
    assert remaining == ["--model", "opus"]

    target_flag, remaining_flag = _parse_combined_args(["--claude", "-v"])
    assert target_flag == "claude"
    assert remaining_flag == ["-v"]


def test_parse_combined_args_codex():
    target, remaining = _parse_combined_args(["codex", "query"])
    assert target == "codex"
    assert remaining == ["query"]

    target_flag, remaining_flag = _parse_combined_args(["-x", "foo"])
    assert target_flag == "codex"
    assert remaining_flag == ["foo"]


def test_parse_combined_args_server():
    target, remaining = _parse_combined_args(["server"])
    assert target == "server"
    assert remaining == []

    target_flag, remaining_flag = _parse_combined_args(["--server"])
    assert target_flag == "server"
    assert remaining_flag == []


def test_select_client_interactively_non_tty():
    with patch("sys.stdin.isatty", return_value=False):
        assert _select_client_interactively() == "claude"


def test_select_client_interactively_tty_choices():
    with (
        patch("sys.stdin.isatty", return_value=True),
        patch("codefa.cli.entrypoints._read_key", side_effect=["down", "enter"]),
    ):
        assert _select_client_interactively() == "codex"

    with (
        patch("sys.stdin.isatty", return_value=True),
        patch("codefa.cli.entrypoints._read_key", side_effect=["down", "down", "enter"]),
    ):
        assert _select_client_interactively() == "server"


def test_combined_launches_server_directly():
    with patch("codefa.cli.commands.serve") as mock_serve:
        combined(["server"])
        mock_serve.assert_called_once()


def test_combined_launches_codex_with_preflight_ok():
    with (
        patch("codefa.cli.launchers.common.preflight_proxy", return_value=None),
        patch("codefa.cli.launchers.codex.launch") as mock_launch_codex,
    ):
        combined(["codex", "--help"])
        mock_launch_codex.assert_called_once_with(["--help"])
