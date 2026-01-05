<div align="center">
  <img src="assets/foshati.jpg" alt="codefa logo" width="120" style="border-radius: 50%;">
  <h1>codefa</h1>
  <p><strong>The High-Performance Local AI Proxy & Control Center for Coding Agents</strong></p>

  <p>
    <a href="https://github.com/Foshati/codefa/releases"><img src="https://img.shields.io/badge/version-5.0.7-blue.svg?style=flat-square" alt="Version"></a>
    <a href="https://python.org"><img src="https://img.shields.io/badge/python-3.14-green.svg?style=flat-square" alt="Python"></a>
    <a href="https://fastapi.tiangolo.com"><img src="https://img.shields.io/badge/FastAPI-0.141-009688.svg?style=flat-square" alt="FastAPI"></a>
    <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-purple.svg?style=flat-square" alt="License"></a>
  </p>
</div>

---

## 🚀 Overview

**`codefa`** is an ultra-fast, local-first proxy and management suite designed to connect autonomous AI coding agents—such as **Claude Code** and **OpenAI Codex**—to any OpenAI-compatible AI provider (NVIDIA NIM, DeepSeek, OpenRouter, Mistral, Ollama, LM Studio, Kimi, MiniMax, and more).

Featuring an interactive terminal launcher, a modern responsive Admin UI on port `8090`, and live HTTP access log streaming, `codefa` gives you total control over model routing, provider API keys, and server diagnostics.

<div align="center">
  <img src="assets/codefa-cli-menu.png" alt="codefa interactive terminal menu" width="750" style="border-radius: 8px;">
  <p><em>Interactive borderless CLI selection menu in terminal</em></p>
</div>

---

## ✨ Features

- ⚡ **Interactive Terminal Launcher (`codefa`)**: Arrow-key navigation (↑/↓) to seamlessly launch **Claude Code**, **Codex CLI**, or **Server Only**.
- 🛠️ **Responsive Admin Control Panel**: Beautiful glassmorphism Web UI running on `http://127.0.0.1:8090/admin` with full Dark & Light mode support.
- 📜 **Live Server Logs Stream**: Complete real-time capture of Uvicorn HTTP access logs, API payloads, and internal routing events.
- 🤖 **Universal Coding Agent Compatibility**: Pre-configured support for both Anthropic Claude Code and OpenAI Codex CLI.
- 🔒 **100% Local & Secure**: API keys remain strictly stored in your local `~/.codefa/.env` file with zero telemetry leakage.
- 🏎️ **Optimized Performance**: Built on Python 3.14, FastAPI, Loguru, and uvloop for minimal resource overhead.

---

## 📦 Installation

#### macOS / Linux
```bash
curl -fsSL https://codefa.foshati.com/install.sh | bash
```

#### Windows PowerShell
```powershell
irm https://codefa.foshati.com/install.ps1 | iex
```

> **Note:** Re-run the installation command anytime to upgrade `codefa` to the latest version.

---

## ⚡ Quick Start

### 1. Launching `codefa`

Run `codefa` in your terminal to open the interactive selection menu:

```bash
codefa
```

Use the **↑** and **↓** arrow keys to highlight your choice, then press **Enter**:

- **Claude Code**: Launches Anthropic Claude Code CLI configured with `codefa` proxy.
- **Codex CLI**: Launches OpenAI Codex CLI configured with `codefa` proxy.
- **Server Only**: Starts the background proxy server and opens the Admin UI on port `8090`.

### Direct Subcommands

You can also bypass the menu and launch directly:

```bash
codefa claude   # Direct launcher for Claude Code
codefa codex    # Direct launcher for Codex CLI
codefa server   # Start server & open Admin UI
codefa-init     # Initialize ~/.codefa/.env config
```

---

## 🎨 Admin UI & Control Center

Access the Admin UI anytime at **[http://127.0.0.1:8090/admin](http://127.0.0.1:8090/admin)**.

### Providers Configuration

Configure API keys, model choices, rate limits, and proxies for all supported AI providers in a responsive, theme-aware Web UI:

<div align="center">
  <img src="assets/codefa-providers.png" alt="codefa Admin UI Providers page" width="800" style="border-radius: 8px;">
</div>

### Live Server Logs

Monitor live HTTP requests, status codes, and routing events in real time:

<div align="center">
  <img src="assets/codefa-admin-logs.png" alt="codefa Admin UI Live Server Logs" width="800" style="border-radius: 8px;">
</div>

---

## 🤖 Coding Agents Integration

### Claude Code

`codefa` automatically injects proxy environment variables for seamless integration with Anthropic Claude Code:

<div align="center">
  <img src="assets/codefa-claude-code.png" alt="Claude Code CLI with codefa proxy" width="800" style="border-radius: 8px;">
</div>

### OpenAI Codex CLI

Run Codex CLI with custom models and local provider routing:

<div align="center">
  <img src="assets/codefa-codex.png" alt="Codex CLI with codefa proxy" width="800" style="border-radius: 8px;">
</div>

<div align="center">
  <img src="assets/codefa-model-picker.png" alt="codefa Model Picker" width="800" style="border-radius: 8px;">
</div>

---

## 🏗️ Architecture & Workflow

`codefa` acts as a local bridge between client protocol requests (Anthropic Messages API & OpenAI Responses API) and downstream AI provider endpoints:

<div align="center">
  <img src="assets/codefa-architecture.png" alt="codefa Architecture & Workflow Diagram" width="850" style="border-radius: 12px;">
</div>

---

## 📄 License

Distributed under the **MIT License**. See `LICENSE` for more information.

<div align="center">
  <p>Created with ❤️ by <a href="https://github.com/Foshati">Foshati</a></p>
</div>
