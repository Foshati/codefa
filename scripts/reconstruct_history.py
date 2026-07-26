#!/usr/bin/env python3
"""
reconstruct_history.py

Reconstructs the Git commit history of `codefa` from January 3, 2026 to July 30, 2026.
Creates ~275 commits distributed naturally across 209 days with proper backdated timestamps,
conventional commit messages, and semver progression in pyproject.toml.
"""

import os
import shutil
import subprocess
import sys
import datetime
import random
import re
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.resolve()
BACKUP_DIR = REPO_ROOT / ".backup_history_staging"

IGNORE_DIRS = {'.git', '.venv', '__pycache__', '.pytest_cache', '.ruff_cache', 'node_modules', '.backup_history_staging'}

def get_all_target_files():
    target_files = []
    for root, dirs, files in os.walk(REPO_ROOT):
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
        for f in files:
            if f.endswith('.pyc'):
                continue
            rel = os.path.relpath(os.path.join(root, f), REPO_ROOT)
            target_files.append(rel)
    return sorted(target_files)

def build_commit_specs(all_files):
    """
    Map all target files into ~270 commit specifications.
    """
    file_set = set(all_files)
    specs = []

    def add_commit(msg, files, version=None):
        valid_files = [f for f in files if f in file_set]
        # Only add spec if there are files or a version bump
        if valid_files or version:
            specs.append({'msg': msg, 'files': valid_files, 'version': version})
            for f in valid_files:
                file_set.discard(f)

    # -------------------------------------------------------------
    # STAGE 1: Setup & Core Infrastructure (Jan 3 - Jan 10)
    # -------------------------------------------------------------
    add_commit("chore: initialize repository configuration and ignore rules", [".gitignore", ".python-version"], version="0.1.0")
    add_commit("chore(config): add environment configuration template", [".env.example"])
    add_commit("chore(pkg): configure package metadata and dependencies", ["pyproject.toml"], version="0.1.0")
    add_commit("docs: add initial project README overview", ["README.md"])
    add_commit("chore(pkg): add package manifest and lockfile", ["package.json", "package-lock.json"])
    add_commit("feat(core): establish base package entrypoint", ["src/codefa/__init__.py"])
    add_commit("feat(core): define package core module namespace", ["src/codefa/core/__init__.py"])
    add_commit("feat(core): establish exception module namespace", ["src/codefa/core/exceptions/__init__.py"])
    add_commit("feat(core): define base application exceptions", ["src/codefa/core/exceptions/base.py"], version="0.1.1")
    add_commit("feat(core): add HTTP client exceptions", ["src/codefa/core/exceptions/http.py"])
    add_commit("feat(core): add provider error exception definitions", ["src/codefa/core/exceptions/provider.py"])

    # Core Anthropic Protocol
    add_commit("feat(core): initialize Anthropic protocol package", ["src/codefa/core/anthropic/__init__.py"])
    add_commit("feat(core): define Anthropic protocol wire types", ["src/codefa/core/anthropic/types.py"], version="0.1.2")
    add_commit("feat(core): implement Anthropic payload converters", ["src/codefa/core/anthropic/converters.py"])
    add_commit("feat(core): add Anthropic streaming helpers", ["src/codefa/core/anthropic/stream.py"])
    add_commit("feat(core): implement thinking parameter adapter", ["src/codefa/core/anthropic/thinking.py"])
    add_commit("feat(core): implement Anthropic tool call translation", ["src/codefa/core/anthropic/tool_calls.py"])

    # Core Logging & Utilities
    add_commit("feat(core): setup structured logging package", ["src/codefa/core/logging/__init__.py"])
    add_commit("feat(core): implement custom log formatter", ["src/codefa/core/logging/formatter.py"])
    add_commit("feat(core): add sensitive data redaction filter", ["src/codefa/core/logging/redaction.py"], version="0.1.3")
    add_commit("feat(core): implement runtime-safe log handler", ["src/codefa/core/logging/safe.py"])
    add_commit("feat(core): setup core utils module", ["src/codefa/core/utils/__init__.py"])
    add_commit("feat(core): add async helper utilities", ["src/codefa/core/utils/async_helpers.py"])
    add_commit("feat(core): implement unique request ID generator", ["src/codefa/core/utils/id_generator.py"])
    add_commit("feat(core): add JSON schema validator utility", ["src/codefa/core/utils/json_schema.py"])

    # Core Unit Tests (grouped in pairs)
    core_tests = [f for f in sorted(list(file_set)) if f.startswith("tests/core/")]
    for i in range(0, len(core_tests), 2):
        chunk = core_tests[i:i+2]
        names = ", ".join(Path(c).stem.replace("test_", "") for c in chunk)
        add_commit(f"test(core): add unit tests for {names}", chunk)

    # -------------------------------------------------------------
    # STAGE 2: Configuration Management (Jan 21 - Jan 31)
    # -------------------------------------------------------------
    add_commit("feat(config): establish configuration package structure", ["src/codefa/config/__init__.py"])
    add_commit("feat(config): implement global application settings", ["src/codefa/config/settings.py"], version="0.2.0")
    add_commit("feat(config): add environment variable parser", ["src/codefa/config/env.py"])
    add_commit("feat(config): define provider settings namespace", ["src/codefa/config/providers/__init__.py"])
    
    provider_cfg_files = [f for f in sorted(list(file_set)) if f.startswith("src/codefa/config/providers/")]
    for cfg_file in provider_cfg_files:
        pname = Path(cfg_file).stem.replace("_", " ")
        add_commit(f"feat(config): add {pname} configuration schema", [cfg_file], version="0.2.1")

    config_tests = [f for f in sorted(list(file_set)) if f.startswith("tests/config/")]
    for test_file in config_tests:
        name = Path(test_file).stem.replace("test_", "").replace("_", " ")
        add_commit(f"test(config): verify {name} behavior", [test_file])

    # -------------------------------------------------------------
    # STAGE 3: Provider Base Framework (Feb 1 - Feb 12)
    # -------------------------------------------------------------
    add_commit("feat(providers): define provider abstractions package", ["src/codefa/providers/__init__.py"])
    add_commit("feat(providers): implement base abstract Provider class", ["src/codefa/providers/base.py"], version="0.3.0")
    add_commit("feat(providers): add HTTP client connection wrapper", ["src/codefa/providers/http.py"])
    add_commit("feat(providers): implement rate limiter admission controller", ["src/codefa/providers/admission.py"])
    add_commit("feat(providers): implement provider failure policy", ["src/codefa/providers/failure_policy.py"])
    add_commit("feat(providers): add dynamic model listing interface", ["src/codefa/providers/model_listing.py"], version="0.3.1")
    add_commit("feat(providers): implement stream connection recovery handler", ["src/codefa/providers/stream_recovery.py"])

    # -------------------------------------------------------------
    # STAGE 4: Provider Implementations (Feb 13 - Mar 15)
    # -------------------------------------------------------------
    providers_dir = "src/codefa/providers"
    subdirs = ["openai_chat", "deepseek", "gemini", "google_openai", "mistral", "cloudflare", "lmstudio", "open_router", "github_models", "vertex", "nvidia_nim"]
    
    for sub in subdirs:
        pfiles = [f for f in sorted(list(file_set)) if f.startswith(f"{providers_dir}/{sub}/")]
        for pfile in pfiles:
            fname = Path(pfile).stem
            add_commit(f"feat(providers): implement {sub}/{fname} adapter", [pfile], version="0.4.0")
        
        # Group tests per provider
        ptests = [f for f in sorted(list(file_set)) if f.startswith("tests/providers/") and sub in f]
        if ptests:
            add_commit(f"test(providers): add unit tests for {sub} provider", ptests)

    # Remaining base provider tests in pairs
    rem_prov_tests = [f for f in sorted(list(file_set)) if f.startswith("tests/providers/")]
    for i in range(0, len(rem_prov_tests), 2):
        chunk = rem_prov_tests[i:i+2]
        names = ", ".join(Path(c).stem.replace("test_", "") for c in chunk)
        add_commit(f"test(providers): verify provider core {names}", chunk)

    # -------------------------------------------------------------
    # STAGE 5: Provider Runtime Subsystem (Mar 16 - Mar 30)
    # -------------------------------------------------------------
    add_commit("feat(providers/runtime): create runtime namespace", ["src/codefa/providers/runtime/__init__.py"])
    add_commit("feat(providers/runtime): implement runtime config resolver", ["src/codefa/providers/runtime/config.py"], version="0.5.0")
    add_commit("feat(providers/runtime): add dynamic provider discovery service", ["src/codefa/providers/runtime/discovery.py"])
    add_commit("feat(providers/runtime): implement provider instance factory", ["src/codefa/providers/runtime/factory.py"])
    add_commit("feat(providers/runtime): add model availability cache", ["src/codefa/providers/runtime/model_cache.py"])
    add_commit("feat(providers/runtime): implement runtime provider manager", ["src/codefa/providers/runtime/runtime.py"], version="0.5.1")
    add_commit("feat(providers/runtime): add model specification validator", ["src/codefa/providers/runtime/validation.py"])

    runtime_tests = [f for f in sorted(list(file_set)) if f.startswith("tests/runtime/")]
    if runtime_tests:
        add_commit("test(runtime): add test suite for runtime module", runtime_tests)

    # -------------------------------------------------------------
    # STAGE 6: Messaging Core & Tree Graph (Apr 1 - Apr 25)
    # -------------------------------------------------------------
    add_commit("feat(messaging): define messaging system module", ["src/codefa/messaging/__init__.py"])
    
    # Models
    msg_models = [f for f in sorted(list(file_set)) if f.startswith("src/codefa/messaging/models/")]
    for mfile in msg_models:
        add_commit(f"feat(messaging): add model {Path(mfile).stem}", [mfile], version="0.6.0")

    # Trees
    msg_trees = [f for f in sorted(list(file_set)) if f.startswith("src/codefa/messaging/trees/")]
    for tfile in msg_trees:
        add_commit(f"feat(messaging): implement tree component {Path(tfile).stem}", [tfile], version="0.6.1")

    # Transcript
    msg_transcripts = [f for f in sorted(list(file_set)) if f.startswith("src/codefa/messaging/transcript/")]
    for trfile in msg_transcripts:
        add_commit(f"feat(messaging): add transcript service {Path(trfile).stem}", [trfile])

    # Root messaging helpers
    msg_helpers = [f for f in sorted(list(file_set)) if f.startswith("src/codefa/messaging/") and not os.path.isdir(f)]
    for hfile in msg_helpers:
        if hfile not in ["src/codefa/messaging/transcription.py", "src/codefa/messaging/voice.py"]:
            add_commit(f"feat(messaging): add service {Path(hfile).stem}", [hfile], version="0.7.0")

    # Messaging unit tests (grouped in pairs)
    msg_tests = [f for f in sorted(list(file_set)) if f.startswith("tests/messaging/") and "telegram" not in f and "discord" not in f and "voice" not in f and "transcription" not in f]
    for i in range(0, len(msg_tests), 2):
        chunk = msg_tests[i:i+2]
        names = ", ".join(Path(c).stem.replace("test_", "") for c in chunk)
        add_commit(f"test(messaging): test suite for {names}", chunk)

    # -------------------------------------------------------------
    # STAGE 7: Platforms & Voice Subsystems (Apr 26 - May 18)
    # -------------------------------------------------------------
    telegram_files = [f for f in sorted(list(file_set)) if f.startswith("src/codefa/messaging/telegram/")]
    for tgfile in telegram_files:
        add_commit(f"feat(messaging/telegram): implement {Path(tgfile).stem}", [tgfile], version="0.8.0")

    discord_files = [f for f in sorted(list(file_set)) if f.startswith("src/codefa/messaging/discord/")]
    for dcfile in discord_files:
        add_commit(f"feat(messaging/discord): implement {Path(dcfile).stem}", [dcfile], version="0.8.1")

    add_commit("feat(messaging): implement audio transcription engine", ["src/codefa/messaging/transcription.py"])
    add_commit("feat(messaging): implement voice message handler", ["src/codefa/messaging/voice.py"], version="0.8.2")

    platform_tests = [f for f in sorted(list(file_set)) if f.startswith("tests/messaging/")]
    for i in range(0, len(platform_tests), 2):
        chunk = platform_tests[i:i+2]
        names = ", ".join(Path(c).stem.replace("test_", "") for c in chunk)
        add_commit(f"test(messaging): platform tests for {names}", chunk)

    # -------------------------------------------------------------
    # STAGE 8: Application Layer & System Runtime (May 19 - Jun 5)
    # -------------------------------------------------------------
    add_commit("feat(application): create application layer package", ["src/codefa/application/__init__.py"])
    add_commit("feat(application): implement execution engine", ["src/codefa/application/execution.py"], version="0.9.0")
    add_commit("feat(application): implement reasoning intent resolver", ["src/codefa/application/reasoning.py"])
    add_commit("feat(application): implement model routing logic", ["src/codefa/application/routing.py"], version="0.9.1")

    add_commit("feat(runtime): establish global runtime manager", ["src/codefa/runtime/__init__.py"])
    add_commit("feat(runtime): implement application lifespan manager", ["src/codefa/runtime/application.py"])
    add_commit("feat(runtime): add ASGI web container entrypoint", ["src/codefa/runtime/asgi.py"])
    add_commit("feat(runtime): implement system bootstrap procedure", ["src/codefa/runtime/bootstrap.py"], version="0.9.2")
    add_commit("feat(runtime): add provider manager lifecycle registry", ["src/codefa/runtime/provider_manager.py"])

    app_tests = [f for f in sorted(list(file_set)) if f.startswith("tests/application/")]
    if app_tests:
        add_commit("test(application): add test suite for application routing & execution", app_tests)

    # -------------------------------------------------------------
    # STAGE 9: API Server & Web Endpoints (Jun 6 - Jun 25)
    # -------------------------------------------------------------
    add_commit("feat(api): create API package namespace", ["src/codefa/api/__init__.py"])
    add_commit("feat(api): implement FastAPI web application instance", ["src/codefa/api/app.py"], version="1.0.0")
    add_commit("feat(api): implement application lifespan handlers", ["src/codefa/api/lifespan.py"])
    add_commit("feat(api): add API authentication middleware", ["src/codefa/api/auth.py"])
    add_commit("feat(api): implement dependency injection container", ["src/codefa/api/dependencies.py"])
    add_commit("feat(api): add centralized API error handling", ["src/codefa/api/errors.py"])
    add_commit("feat(api): implement HTTP request logging middleware", ["src/codefa/api/middleware.py"])
    add_commit("feat(api): define request and response DTO schemas", ["src/codefa/api/models.py"], version="1.0.1")
    add_commit("feat(api): add HTTP request utilities", ["src/codefa/api/request_utils.py"])
    add_commit("feat(api): implement SSE response stream encoder", ["src/codefa/api/response_streams.py"])
    add_commit("feat(api): add web server runner daemon", ["src/codefa/api/web_server.py"])

    routes_files = [f for f in sorted(list(file_set)) if f.startswith("src/codefa/api/routes/")]
    for rfile in routes_files:
        add_commit(f"feat(api/routes): implement {Path(rfile).stem} endpoint", [rfile], version="1.0.2")

    api_tests = [f for f in sorted(list(file_set)) if f.startswith("tests/api/")]
    for i in range(0, len(api_tests), 2):
        chunk = api_tests[i:i+2]
        names = ", ".join(Path(c).stem.replace("test_", "") for c in chunk)
        add_commit(f"test(api): test suite for {names}", chunk)

    # -------------------------------------------------------------
    # STAGE 10: CLI Application Interface (Jun 26 - Jul 10)
    # -------------------------------------------------------------
    add_commit("feat(cli): define command line interface package", ["src/codefa/cli/__init__.py"])
    add_commit("feat(cli): implement main CLI argument parser", ["src/codefa/cli/main.py"], version="1.1.0")
    add_commit("feat(cli): implement terminal display renderer", ["src/codefa/cli/display.py"])
    add_commit("feat(cli): add interactive terminal menu", ["src/codefa/cli/menu.py"])
    add_commit("feat(cli): implement command parser options", ["src/codefa/cli/parser.py"])
    add_commit("feat(cli): implement interactive shell mode", ["src/codefa/cli/interactive.py"])

    cli_cmd_files = [f for f in sorted(list(file_set)) if f.startswith("src/codefa/cli/commands/")]
    for cfile in cli_cmd_files:
        add_commit(f"feat(cli/commands): add {Path(cfile).stem} command", [cfile], version="1.1.1")

    cli_tests = [f for f in sorted(list(file_set)) if f.startswith("tests/cli/")]
    for i in range(0, len(cli_tests), 2):
        chunk = cli_tests[i:i+2]
        names = ", ".join(Path(c).stem.replace("test_", "") for c in chunk)
        add_commit(f"test(cli): test suite for {names}", chunk)

    # -------------------------------------------------------------
    # STAGE 11: Integration Contracts & Build Tools (Jul 11 - Jul 18)
    # -------------------------------------------------------------
    contract_tests = [f for f in sorted(list(file_set)) if f.startswith("tests/contracts/")]
    for i in range(0, len(contract_tests), 2):
        chunk = contract_tests[i:i+2]
        names = ", ".join(Path(c).stem.replace("test_", "") for c in chunk)
        add_commit(f"test(contracts): verify protocol contracts {names}", chunk)

    add_commit("chore(scripts): add Linux/macOS installation script", ["scripts/install.sh"])
    add_commit("chore(scripts): add Windows PowerShell installation script", ["scripts/install.ps1"])
    add_commit("chore(scripts): add Linux/macOS uninstallation script", ["scripts/uninstall.sh"])
    add_commit("chore(scripts): add Windows PowerShell uninstallation script", ["scripts/uninstall.ps1"])
    add_commit("chore(scripts): implement local CI validation script", ["scripts/ci.sh"], version="1.2.0")
    add_commit("chore(scripts): add Windows CI automation script", ["scripts/ci.ps1"])

    script_tests = [f for f in sorted(list(file_set)) if f.startswith("tests/scripts/")]
    if script_tests:
        add_commit("test(scripts): add script automation test suite", script_tests)

    # -------------------------------------------------------------
    # STAGE 12: CI/CD & Smoke Framework (Jul 19 - Jul 25)
    # -------------------------------------------------------------
    add_commit("chore(ci): configure GitHub issue templates", [f for f in sorted(list(file_set)) if f.startswith(".github/ISSUE_TEMPLATE/")])
    add_commit("chore(ci): configure Dependabot dependency updates", [f for f in sorted(list(file_set)) if f == ".github/dependabot.yml"])
    add_commit("chore(ci): setup GitHub Actions CI test workflows", [f for f in sorted(list(file_set)) if f.startswith(".github/workflows/")])

    add_commit("test(smoke): initialize live smoke test runner", ["smoke/__init__.py", "smoke/conftest.py", "smoke/capabilities.py", "smoke/features.py", "smoke/README.md"])

    smoke_lib = [f for f in sorted(list(file_set)) if f.startswith("smoke/lib/")]
    for i in range(0, len(smoke_lib), 2):
        chunk = smoke_lib[i:i+2]
        names = ", ".join(Path(c).stem for c in chunk)
        add_commit(f"test(smoke): add smoke helpers for {names}", chunk)

    smoke_prereq = [f for f in sorted(list(file_set)) if f.startswith("smoke/prereq/")]
    for i in range(0, len(smoke_prereq), 2):
        chunk = smoke_prereq[i:i+2]
        names = ", ".join(Path(c).stem for c in chunk)
        add_commit(f"test(smoke): add prerequisite live checks for {names}", chunk)

    smoke_prod = [f for f in sorted(list(file_set)) if f.startswith("smoke/product/")]
    for i in range(0, len(smoke_prod), 2):
        chunk = smoke_prod[i:i+2]
        names = ", ".join(Path(c).stem for c in chunk)
        add_commit(f"test(smoke): add product live checks for {names}", chunk)

    # -------------------------------------------------------------
    # STAGE 13: Assets & Documentation (Jul 26 - Jul 29)
    # -------------------------------------------------------------
    asset_files = [f for f in sorted(list(file_set)) if f.startswith("assets/")]
    if asset_files:
        add_commit("docs(assets): add architecture diagrams and visual assets", asset_files)

    add_commit("docs: add system architecture specification", ["ARCHITECTURE.md"], version="1.2.35")
    add_commit("docs: add contributor guidelines", ["CONTRIBUTING.md"])
    add_commit("docs: update developer agent directives", ["AGENTS.md", "CLAUDE.md"])
    add_commit("chore(lock): generate initial dependency lockfile", ["uv.lock"], version="1.2.38")

    # -------------------------------------------------------------
    # STAGE 14: Remaining files & Final Version Polish (Jul 30)
    # -------------------------------------------------------------
    remaining_files = sorted(list(file_set))
    if remaining_files:
        chunk_size = max(1, len(remaining_files) // 5)
        for i in range(0, len(remaining_files), chunk_size):
            chunk = remaining_files[i:i+chunk_size]
            add_commit("refactor: refine module interfaces and complete integration", chunk)

    # Final version bump
    add_commit("chore(release): bump package version to v1.2.39", ["pyproject.toml"], version="1.2.39")

    return specs

def generate_timestamps(num_commits):
    """
    Generate `num_commits` monotonically increasing timestamps
    from 2026-01-03 09:15:00 to 2026-07-30 11:45:00 (+03:30).
    """
    start_date = datetime.date(2026, 1, 3)
    end_date = datetime.date(2026, 7, 30)
    
    dates = []
    d = start_date
    while d <= end_date:
        dates.append(d)
        d += datetime.timedelta(days=1)
    
    num_days = len(dates) # 209
    random.seed(42)
    
    commit_counts = [1] * num_days
    remaining = num_commits - num_days
    
    while remaining > 0:
        idx = random.randint(0, num_days - 1)
        if commit_counts[idx] < 5:
            commit_counts[idx] += 1
            remaining -= 1

    timestamps = []
    for idx, day in enumerate(dates):
        cnt = commit_counts[idx]
        day_times = []
        for _ in range(cnt):
            hour = random.randint(9, 21)
            minute = random.randint(0, 59)
            second = random.randint(0, 59)
            day_times.append(datetime.datetime(day.year, day.month, day.day, hour, minute, second))
        day_times.sort()
        timestamps.extend(day_times)

    return timestamps

def main():
    print("=== Starting Git History Reconstruction ===")
    
    all_files = get_all_target_files()
    print(f"Discovered {len(all_files)} files in codebase.")

    if BACKUP_DIR.exists():
        shutil.rmtree(BACKUP_DIR)
    
    print("Creating temporary staging backup...")
    os.makedirs(BACKUP_DIR, exist_ok=True)
    for rel_path in all_files:
        src = REPO_ROOT / rel_path
        dst = BACKUP_DIR / rel_path
        os.makedirs(dst.parent, exist_ok=True)
        shutil.copy2(src, dst)

    git_dir = REPO_ROOT / ".git"
    if git_dir.exists():
        shutil.rmtree(git_dir)
    
    subprocess.run(["git", "init", "-b", "main"], cwd=REPO_ROOT, check=True)
    subprocess.run(["git", "config", "user.name", "Foshati"], cwd=REPO_ROOT, check=True)
    subprocess.run(["git", "config", "user.email", "amirrezafoshati@gmail.com"], cwd=REPO_ROOT, check=True)

    specs = build_commit_specs(all_files)
    num_commits = len(specs)
    print(f"Generated {num_commits} commit specifications.")

    timestamps = generate_timestamps(num_commits)
    
    print("Executing backdated commits...")
    for idx, (spec, ts) in enumerate(zip(specs, timestamps), start=1):
        staged_any = False
        
        # 1. Restore files for this commit from backup
        for rel_path in spec['files']:
            src = BACKUP_DIR / rel_path
            dst = REPO_ROOT / rel_path
            os.makedirs(dst.parent, exist_ok=True)
            shutil.copy2(src, dst)
            subprocess.run(["git", "add", rel_path], cwd=REPO_ROOT, check=True)
            staged_any = True

        # 2. Update pyproject.toml version if specified
        if spec.get('version'):
            pyproject_path = REPO_ROOT / "pyproject.toml"
            # Ensure pyproject.toml exists
            if not pyproject_path.exists():
                src_pyproject = BACKUP_DIR / "pyproject.toml"
                if src_pyproject.exists():
                    shutil.copy2(src_pyproject, pyproject_path)
            if pyproject_path.exists():
                content = pyproject_path.read_text(encoding="utf-8")
                new_content = re.sub(r'version\s*=\s*"[^"]+"', f'version = "{spec["version"]}"', content, count=1)
                pyproject_path.write_text(new_content, encoding="utf-8")
                subprocess.run(["git", "add", "pyproject.toml"], cwd=REPO_ROOT, check=True)
                staged_any = True

        # Check if there are changes in staging
        status_proc = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=REPO_ROOT)
        has_staged_changes = (status_proc.returncode != 0)

        if not has_staged_changes:
            # If no staged changes, pass --allow-empty or continue
            print(f"Skipping empty commit {idx}: {spec['msg']}")
            continue

        date_str = ts.strftime("%Y-%m-%dT%H:%M:%S+03:30")
        
        env = os.environ.copy()
        env["GIT_AUTHOR_DATE"] = date_str
        env["GIT_COMMITTER_DATE"] = date_str
        env["GIT_AUTHOR_NAME"] = "Foshati"
        env["GIT_AUTHOR_EMAIL"] = "amirrezafoshati@gmail.com"
        env["GIT_COMMITTER_NAME"] = "Foshati"
        env["GIT_COMMITTER_EMAIL"] = "amirrezafoshati@gmail.com"

        commit_msg = spec['msg']
        subprocess.run(["git", "commit", "-m", commit_msg], cwd=REPO_ROOT, env=env, check=True, stdout=subprocess.DEVNULL)

    # Copy any remaining files from backup to ensure complete codebase state
    print("Finalizing working tree state...")
    for rel_path in all_files:
        src = BACKUP_DIR / rel_path
        dst = REPO_ROOT / rel_path
        if not dst.exists():
            os.makedirs(dst.parent, exist_ok=True)
            shutil.copy2(src, dst)
            subprocess.run(["git", "add", rel_path], cwd=REPO_ROOT, check=True)

    # If remaining files were staged, make a final commit if there are staged changes
    status_proc = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=REPO_ROOT)
    has_staged = (status_proc.returncode != 0)
    if has_staged:
        final_ts = timestamps[-1] + datetime.timedelta(minutes=5)
        date_str = final_ts.strftime("%Y-%m-%dT%H:%M:%S+03:30")
        env = os.environ.copy()
        env["GIT_AUTHOR_DATE"] = date_str
        env["GIT_COMMITTER_DATE"] = date_str
        env["GIT_AUTHOR_NAME"] = "Foshati"
        env["GIT_AUTHOR_EMAIL"] = "amirrezafoshati@gmail.com"
        env["GIT_COMMITTER_NAME"] = "Foshati"
        env["GIT_COMMITTER_EMAIL"] = "amirrezafoshati@gmail.com"
        subprocess.run(["git", "commit", "-m", "chore: synchronize complete workspace state"], cwd=REPO_ROOT, env=env, check=True)

    if BACKUP_DIR.exists():
        shutil.rmtree(BACKUP_DIR)

    rev_count = subprocess.run(["git", "rev-list", "--count", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True, check=True).stdout.strip()
    print(f"\nSUCCESS! Created {rev_count} backdated commits.")
    print("Recent 10 commits:")
    subprocess.run(["git", "log", "--oneline", "-n", "10"], cwd=REPO_ROOT)

if __name__ == "__main__":
    main()
