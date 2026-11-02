# Changelog

All notable changes to **AURA** will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-11-02

### Added
- Initial release of **AURA (Advanced Universal Reactive Agent)**.
- 8 Autonomous Agent Harnesses:
  - `native_openhands` (CodeAct): Autonomous Python code execution and file I/O agent.
  - `deep_research`: Multi-step citation-backed research agent across web search and local files.
  - `native_react`: Thought-Action-Observation reasoning agent.
  - `monitor_operative`: Continuous background monitor with long-horizon memory and compression.
  - `morning_digest`: Daily automated briefing across calendar, emails, and news with neural voice synthesis.
  - `orchestrator`: Multi-turn planner with automatic tool selection.
  - `operative`: Persistent autonomous stateful agent.
  - `simple`: Fast, zero-overhead conversational chat.
- Dual Interface:
  - Interactive React 19 + Tailwind Web GUI.
  - Command-line interface (`aura`).
- Multi-engine inference support:
  - Local: Ollama, vLLM, LM Studio, llama.cpp, Exo, Nexa.
  - Cloud: Google Gemini, OpenAI, Anthropic, DeepSeek, NVIDIA NIM.
- Model Context Protocol (MCP) and extensible skills integration.
- Built-in on-device speech-to-text with faster-whisper.
- Production REST API server compatible with OpenAI `/v1/chat/completions`.
