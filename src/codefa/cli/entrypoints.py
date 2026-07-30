# ruff: noqa: RUF001
"""Lightweight entry points for installed Free Claude Code commands."""

import sys
from collections.abc import Sequence

from codefa.core.version import package_version


def serve(argv: Sequence[str] | None = None) -> None:
    """Start the FastAPI server (registered as ``codefa-server``)."""
    if _print_version_if_requested(argv):
        return

    # Keep the server composition root off metadata-only command paths.
    from codefa.cli.commands import serve as run_server

    run_server()


def combined(argv: Sequence[str] | None = None) -> None:
    """Run codefa with interactive client selection or explicit subcommand/flag."""
    try:
        _run_combined(argv)
    except KeyboardInterrupt:
        from rich.console import Console

        Console().print("\n[bold yellow]👋 Goodbye![/bold yellow]\n")
        raise SystemExit(0) from None


def _run_combined(argv: Sequence[str] | None = None) -> None:
    import os
    import subprocess
    import time

    from codefa.cli.launchers.common import preflight_proxy
    from codefa.config.server_urls import local_proxy_root_url
    from codefa.config.settings import get_settings

    if _print_version_if_requested(argv):
        return

    target_client, remaining_args = _parse_combined_args(argv)
    if target_client is None:
        target_client = _select_client_interactively()

    if target_client == "server":
        from codefa.cli.commands import serve as run_server

        run_server()
        return

    settings = get_settings()
    proxy_root_url = local_proxy_root_url(settings)

    server_process = None
    if preflight_proxy(proxy_root_url) is not None:
        print("Starting codefa-server in the background...", flush=True)
        server_process = subprocess.Popen(
            [sys.executable, "-c", "from codefa.cli.entrypoints import serve; serve()"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=os.environ.copy(),
        )

        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            if preflight_proxy(proxy_root_url) is None:
                break
            time.sleep(0.1)
        else:
            print("Error: codefa-server failed to start in time.", file=sys.stderr)
            if server_process.poll() is None:
                server_process.terminate()
            raise SystemExit(1)

    try:
        if target_client == "codex":
            from codefa.cli.launchers.codex import launch as launch_codex

            launch_codex(remaining_args)
        else:
            from codefa.cli.launchers.claude import launch as launch_claude

            launch_claude(remaining_args)
    finally:
        if server_process is not None and server_process.poll() is None:
            server_process.terminate()
            try:
                server_process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                server_process.kill()


def _parse_combined_args(argv: Sequence[str] | None) -> tuple[str | None, list[str]]:
    raw_args = list(sys.argv[1:] if argv is None else argv)
    if not raw_args:
        return None, []

    target_client = None
    remaining: list[str] = []

    for arg in raw_args:
        arg_lower = arg.lower()
        if target_client is None and arg_lower in (
            "claude",
            "codefa-claude",
            "--claude",
            "-c",
        ):
            target_client = "claude"
        elif target_client is None and arg_lower in (
            "codex",
            "codefax",
            "--codex",
            "-x",
        ):
            target_client = "codex"
        elif target_client is None and arg_lower in (
            "server",
            "codefa-server",
            "--server",
            "-s",
        ):
            target_client = "server"
        else:
            remaining.append(arg)

    return target_client, remaining


def _select_client_interactively() -> str:
    if not sys.stdin.isatty():
        return "claude"

    options = [
        ("claude", "Claude Code", "Anthropic Claude Code CLI"),
        ("codex", "Codex CLI", "OpenAI Codex CLI"),
        ("server", "Server Only", "Start Admin UI & Proxy on port 8090"),
    ]

    selected_index = 0

    from rich.console import Console, Group
    from rich.live import Live
    from rich.text import Text

    console = Console(highlight=False)
    version = package_version()

    def make_renderable(idx: int) -> Group:
        lines = [
            f"[bold cyan]codefa[/bold cyan] [dim]v{version}[/dim] — [bold white]AI Coding Assistant[/bold white]",
            "[dim]Use ↑/↓ arrow keys to select, press Enter to confirm:[/dim]",
            "",
        ]
        for i, (_key, title, desc) in enumerate(options):
            if i == idx:
                lines.append(
                    f"  [bold green]❯ {title:<14}[/bold green] [bold white]{desc}[/bold white]"
                )
            else:
                lines.append(f"    [dim]{title:<14} {desc}[/dim]")

        return Group(*[Text.from_markup(line) for line in lines])

    try:
        with Live(
            make_renderable(selected_index),
            console=console,
            auto_refresh=False,
            transient=True,
        ) as live:
            while True:
                key = _read_key()
                if key == "up":
                    selected_index = (selected_index - 1) % len(options)
                    live.update(make_renderable(selected_index), refresh=True)
                elif key == "down":
                    selected_index = (selected_index + 1) % len(options)
                    live.update(make_renderable(selected_index), refresh=True)
                elif key in ("enter", "space"):
                    break
                elif key.isdigit() and 1 <= int(key) <= len(options):
                    selected_index = int(key) - 1
                    break
    except KeyboardInterrupt:
        raise
    except Exception:
        pass

    target_key, target_title, _ = options[selected_index]
    console.print(
        f"[bold cyan]codefa[/bold cyan] [dim]v{version}[/dim] → [bold green]{target_title}[/bold green]\n",
        highlight=False,
    )
    return target_key


def _read_key() -> str:
    """Read a single keypress or arrow key (cross-platform)."""
    if sys.platform == "win32":
        import msvcrt

        ch = msvcrt.getch()
        if ch in (b"\x00", b"\xe0"):
            ch2 = msvcrt.getch()
            if ch2 == b"H":
                return "up"
            if ch2 == b"P":
                return "down"
        if ch in (b"\r", b"\n"):
            return "enter"
        if ch == b" ":
            return "space"
        return ch.decode("utf-8", errors="ignore")

    import termios
    import tty

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
        if ch == "\x1b":
            ch2 = sys.stdin.read(1)
            if ch2 == "[":
                ch3 = sys.stdin.read(1)
                if ch3 == "A":
                    return "up"
                if ch3 == "B":
                    return "down"
        if ch in ("\r", "\n"):
            return "enter"
        if ch == " ":
            return "space"
        if ch == "\x03":
            raise KeyboardInterrupt()
        return ch
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def init(argv: Sequence[str] | None = None) -> None:
    """Scaffold config at ~/.codefa/.env (registered as ``codefa-init``)."""
    if _print_version_if_requested(argv):
        return

    # Config initialization shares command infrastructure with the server.
    from codefa.cli.commands import init as initialize_config

    initialize_config()


def _print_version_if_requested(argv: Sequence[str] | None) -> bool:
    args = sys.argv[1:] if argv is None else argv
    if "--version" not in args:
        return False
    print(f"codefa {package_version()}")
    return True
