# Contributing to AURA

Thank you for your interest in contributing to AURA! We welcome contributions of all kinds — from bug fixes and documentation improvements to new agent capabilities and engine integrations.

---

## 🛠️ Development Setup

1. **Fork and Clone**:
   ```bash
   git clone https://github.com/Rohitpvt/AURA-Agentic-AI.git
   cd AURA-Agentic-AI
   ```

2. **Set up the Python Environment**:
   We use [uv](https://docs.astral.sh/uv/) for dependency management:
   ```bash
   uv sync --extra dev --extra server --extra desktop
   uv run pre-commit install
   ```

3. **Run Tests**:
   ```bash
   uv run pytest tests/ -v
   ```

4. **Lint & Code Style**:
   We use `ruff`:
   ```bash
   uv run ruff check src/ tests/
   uv run ruff format src/ tests/
   ```

---

## 💡 Contribution Guidelines

- **Code Quality**: Keep changes minimal, clean, well-tested, and documented.
- **Pull Requests**:
  1. Create a feature branch: `git checkout -b feature/my-new-feature`
  2. Commit your changes: `git commit -m "Add new feature"`
  3. Push to your branch: `git push origin feature/my-new-feature`
  4. Open a Pull Request on GitHub.

Thank you for helping make AURA better!
