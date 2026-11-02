# AURA — Agentic AI

<div align="center">
  <h3><i>Personal, Private & Autonomous AI — On Your Devices.</i></h3>

  <p>
    <a href="https://github.com/Rohitpvt/AURA-Agentic-AI"><img src="https://img.shields.io/badge/GitHub-Rohitpvt%2FAURA--Agentic--AI-blue?logo=github" alt="Repository"></a>
    <img src="https://img.shields.io/badge/Python-%3E%3D3.10-blue" alt="Python">
    <img src="https://img.shields.io/badge/License-Apache%202.0-green" alt="License">
    <img src="https://img.shields.io/badge/UI-React%2019%20%2B%20Tailwind-purple" alt="Frontend">
  </p>
</div>

---

## 🌟 Overview

**AURA (Advanced Universal Reactive Agent)** is a framework for local-first, privacy-respecting personal AI agents. Built with modular intelligence primitives, AURA allows you to run powerful autonomous agents directly on your own hardware using local LLM engines (Ollama, vLLM, LM Studio, llama.cpp), while offering seamless hybrid fallback to cloud providers (Google Gemini, OpenAI, Anthropic, DeepSeek).

Whether you need a full-screen local web GUI, an interactive terminal chat, automated task execution, or multi-hop deep research across your documents, AURA provides the complete agentic harness.

---

## ✨ Key Features

- **Local-First & Private**: Run 100% locally on your machine with zero data leakage. Works with Ollama, LM Studio, vLLM, and llama.cpp.
- **Hybrid Cloud Intelligence**: Effortlessly switch to or combine with Google Gemini (`gemini-2.5-flash`, `gemini-3-flash`), OpenAI (`gpt-4o`, `o3-mini`), Anthropic (`claude-3-5-sonnet`), and NVIDIA NIM.
- **8 Autonomous Agent Loops**:
  - `native_openhands` (CodeAct): Autonomous Python code execution and file I/O agent.
  - `deep_research`: Multi-step citation-backed research agent across web search and local files.
  - `native_react`: Thought-Action-Observation reasoning agent.
  - `monitor_operative`: Continuous background monitor with long-horizon memory and compression.
  - `morning_digest`: Daily automated briefing across calendar, emails, and news with neural voice synthesis.
  - `orchestrator`: Multi-turn planner with automatic tool selection.
  - `operative`: Persistent autonomous stateful agent.
  - `simple`: Fast, zero-overhead conversational chat.
- **Model Context Protocol (MCP) & Extensible Skills**: Out-of-the-box MCP server integration, plus tools for web search, document parsing, system monitoring, and bash/powershell command execution.
- **Modern Web GUI + Voice**: Beautiful React 19 + Vite + Tailwind CSS browser interface with LaTeX rendering (KaTeX), real-time streaming, and on-device speech-to-text (`faster-whisper`).
- **Production REST API Server**: Fast OpenAI-compatible `/v1/chat/completions` server with WebSocket streaming.

---

## 🚀 Quick Start

### 1. Prerequisites
- **Git**
- **Python 3.10 - 3.13** (Managed automatically via `uv`)
- **Node.js 22+** (for building/running the Web GUI)

### 2. Clone the Repository
```bash
git clone https://github.com/Rohitpvt/AURA-Agentic-AI.git
cd AURA-Agentic-AI
```

### 3. Install Dependencies
Using [uv](https://docs.astral.sh/uv/) for lightning-fast environment setup:
```bash
# Install uv (if not already installed)
powershell -ExecutionPolicy ByPass -Command "irm https://astral.sh/uv/install.ps1 | iex"

# Sync dependencies and build virtual environment
uv sync --extra server --extra desktop --extra tools-search --extra inference-cloud --extra inference-google
```

### 4. Build the Web Frontend (Optional for GUI)
```bash
cd frontend
npm install --engine-strict=false
npm run build
cd ..
```

---

## 💻 Running AURA

### One-Click Launchers (Windows)
- **`.\run-gui.bat`**: Starts the backend server and opens the browser interface.
- **`.\aura.bat`**: CLI entry point (e.g. `.\aura.bat chat`, `.\aura.bat doctor`).

### CLI Commands
```bash
# Start the graphical browser interface
uv run aura gui

# Start an interactive multi-turn terminal chat
uv run aura chat

# Ask a direct question
uv run aura ask "Summarize the latest developments in quantum computing."

# Run diagnostic health check
uv run aura doctor

# Start OpenAI-compatible API server on http://127.0.0.1:8000
uv run aura serve
```

---

## ⚙️ Configuration & Model Setup

Configuration is stored in `~/.aura/config.toml` (or `~/.openjarvis/config.toml`).

Initialize a starter configuration:
```bash
uv run aura init --preset chat-simple --force
```

### Using Local Models (Ollama)
1. Install [Ollama](https://ollama.com).
2. Pull a model:
   ```bash
   ollama pull qwen3.5:4b
   ```
3. AURA will automatically detect and route to your running Ollama instance.

### Using Cloud APIs (Gemini, OpenAI, Anthropic)
Set your environment variables in your terminal:
```powershell
$env:GEMINI_API_KEY = "your-api-key"
# or
$env:OPENAI_API_KEY = "your-api-key"
# or
$env:ANTHROPIC_API_KEY = "your-api-key"
```

---

## 🏗️ Architecture

```
AURA-Agentic-AI/
├── src/
│   └── openjarvis/          # Core backend framework
│       ├── agents/          # Autonomous agent implementations
│       ├── cli/             # Click-based CLI commands (aura)
│       ├── engine/          # Local & cloud inference drivers
│       ├── memory/          # Vector & SQLite memory systems
│       ├── tools/           # MCP tools, web search, execution tools
│       ├── server/          # FastAPI REST & WebSocket server
│       └── speech/          # Faster-whisper audio & STT
├── frontend/                # React 19 + Vite + Tailwind graphical interface
├── configs/                 # Preset configurations & prompts
├── tests/                   # Pytest test suite
├── aura.bat                 # Windows quick launcher
└── run-gui.bat              # One-click GUI launcher
```

---

## 👤 Author

- **Rohit** — [GitHub (@Rohitpvt)](https://github.com/Rohitpvt)
- Repository: [https://github.com/Rohitpvt/AURA-Agentic-AI](https://github.com/Rohitpvt/AURA-Agentic-AI)

## 📄 License

This project is licensed under the Apache License 2.0 — see the [LICENSE](LICENSE) file for details.
