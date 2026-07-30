# 📋 CHANGELOG

All notable changes to **codefa** will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [v1.2.50] - 2026-07-30
- **Automated GitHub Releases**: Integrated GitHub Actions release workflow and full `CHANGELOG.md` documentation.
- **Vibrant Gradient Logo**: Updated `assets/codefa.svg` with modern electric blue (`#2563eb` -> `#38bdf8`) gradient.
- **Unified Version Color**: Disabled automatic number highlighting in CLI launcher to render version headers in single dim grey.

## [v1.2.48] - 2026-07-30
- **Real-Time Checkmark Transformation**: When answering `[Y/n]` prompts, the `?` question mark instantly morphs into a green `✔` checkmark upon user confirmation.

## [v1.2.46] - 2026-07-30
- **Simplified Completion Guidance**: Streamlined terminal output to eliminate duplicate status lines.

## [v1.2.44] - 2026-07-30
- **Piped TTY Interactive Prompting**: Direct `/dev/tty` reading enables interactive prompts even when executing via `curl -fsSL https://codefa.foshati.com/install.sh | bash`.
- **Animated Loading Spinner**: Added Cyan `⠋ ⠙ ⠹` ASCII spinner during package downloads and tool installations.

## [v1.2.42] - 2026-07-30
- **Interactive Prompts for Native CLIs**: Added prompt choices before installing optional Claude Code and Codex CLIs.

## [v1.2.40] - 2026-07-30
- **Interactive Assistant Chooser (`codefa`)**: Added borderless interactive terminal menu for selecting coding agents.

## [v1.2.39] - 2026-07-30
- **CI Contract Validation**: Updated README badges, SVG references, and GitHub Actions checks.

## [v1.2.35] - 2026-07-30
- **Claude Code Preflight Integration**: Enforced auto-proxy fallback and environment configuration.

## [v1.2.30] - 2026-07-30
- **Codex Model Catalog**: Dynamic TOML model registry generation for Codex CLI.

## [v1.2.25] - 2026-07-30
- **Process Isolation**: Prevents port conflicts and manages background daemon processes cleanly.

## [v1.2.20] - 2026-07-30
- **Dynamic PATH Auto-Configuration**: Automatically registers `$HOME/.local/bin` and `uv` tool binaries in shell PATH.

## [v1.2.15] - 2026-07-30
- **Cross-Platform Installers**: Native `install.sh` for macOS/Linux and `install.ps1` for Windows PowerShell.

## [v1.2.10] - 2026-07-30
- **Standalone `uv` Tool Packaging**: Bundled entry points (`codefa`, `codefa-server`, `codefa-claude`, `codefax`).

## [v1.2.5] - 2026-07-30
- **Automated CI Quality Gates**: Added Ruff formatting, type checking (`ty`), and pytest suites.

## [v1.2.0] - 2026-07-30
- **Multi-Agent Proxy Adapter**: Unified protocol translation layer supporting Claude Code and Codex CLI.

## [v1.1.30] - 2026-07-30
- **Performance Caching**: Fast request routing and zero-copy string buffer assembly.

## [v1.1.25] - 2026-07-30
- **System Directives**: Custom prompt overriding and provider-level system message formatting.

## [v1.1.20] - 2026-07-30
- **Model Fallback Routing**: Automatic provider failover on HTTP quota/rate-limit errors.

## [v1.1.15] - 2026-07-30
- **Voice Extensions**: Added speech-to-text / text-to-speech integration modules.

## [v1.1.10] - 2026-07-30
- **Multi-Provider Hub**: Native support for DeepSeek, OpenRouter, Mistral, Ollama, LM Studio, and Kimi.

## [v1.1.5] - 2026-07-30
- **NVIDIA NIM Gateway**: Specialized adapter for high-throughput NVIDIA NIM endpoints.

## [v1.1.0] - 2026-07-30
- **Admin Control UI**: Modern web dashboard on port `8090` with real-time log streaming and API key manager.

## [v1.0.5] - 2026-07-30
- **OpenAI & Anthropic Mapping**: Wire error translation and stream event serialization.

## [v1.0.0] - 2026-07-01
- **Initial Release**: Core high-performance local AI proxy architecture for autonomous coding agents.
