# Local Development Setup Guide (SETUP_GUIDE.md)
## Project Name: AURA (Autonomous Universal Reactive Agent)
**Document Version:** 2.0.0  
**Phase:** Phase 0.5 — Zero-Cost Architecture Reconciliation & Invariant Audit  
**Classification:** Zero-Cost Local Engineering Setup Guide  

---

## 1. System Prerequisites

Verify that your local personal computer has the following free/open-source tools installed:

| Dependency | Minimum Version | Installation & Verification |
| :--- | :--- | :--- |
| **Python** | 3.12+ | `python --version` |
| **Node.js & npm** | Node 20+ LTS / npm 10+ | `node -v && npm -v` |
| **Ollama** | 0.5+ | [ollama.com](https://ollama.com) $\rightarrow$ `ollama --version` |
| **PostgreSQL** | 16+ (with `pgvector`, `pgcrypto`) | `psql --version` |
| **Docker Engine / WSL2**| Docker Desktop / WSL2 on Windows | `docker --version` or `wsl --status` |
| **Git** | 2.40+ | `git --version` |

---

## 2. Pulling Free Local LLM Models (Ollama)

Execute the following commands to pull the recommended quantized models:

```bash
# 1. Primary General & Tool-Calling Model (Size: ~4.7 GB)
ollama pull qwen2.5:7b-instruct-q4_K_M

# 2. Fast Routine Extraction & Memory Model (Size: ~2.0 GB - Fits 100% in 4GB VRAM)
ollama pull llama3.2:3b-instruct-q4_K_M

# (Note: Local semantic embeddings are automatically generated via FastEmbed using BAAI/bge-base-en-v1.5 on CPU)
```

---

## 3. Environment Configuration (`.env`)

Create `.env` in the project root. **Notice: ZERO paid API keys are required!**

```bash
# ==============================================================================
# AURA CONTROL PLANE CONFIGURATION (100% LOCAL & ZERO COST)
# ==============================================================================
AURA_ENV=development
AURA_SECRET_KEY=local_development_secret_key_64_characters_long_abcdef123456
AURA_API_PORT=8000
AURA_WEB_PORT=3000

# ==============================================================================
# LOCAL DATABASE & PGVECTOR
# ==============================================================================
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/aura_db

# ==============================================================================
# LOCAL LLM RUNTIME (OLLAMA)
# ==============================================================================
OLLAMA_BASE_URL=http://localhost:11434/v1
LOCAL_MODEL_GENERAL=qwen2.5:7b-instruct-q4_K_M
LOCAL_MODEL_FAST=llama3.2:3b-instruct-q4_K_M
FASTEMBED_MODEL_NAME=BAAI/bge-base-en-v1.5

# ==============================================================================
# LOCAL SANDBOX & BROWSER
# ==============================================================================
PLAYWRIGHT_HEADLESS=true
SANDBOX_DOCKER_IMAGE=aura-sandbox:latest
```

---

## 4. Step-by-Step Local Setup

### Step 4.1: PostgreSQL & pgvector Setup
```bash
# Connect to local PostgreSQL and create database with extensions
psql -U postgres -c "CREATE DATABASE aura_db;"
psql -U postgres -d aura_db -c "CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\";"
psql -U postgres -d aura_db -c "CREATE EXTENSION IF NOT EXISTS \"pgcrypto\";"
psql -U postgres -d aura_db -c "CREATE EXTENSION IF NOT EXISTS \"vector\";"
```

### Step 4.2: Backend Control Plane Setup (FastAPI)
```bash
cd apps/api
python -m venv .venv

# On Windows PowerShell:
.venv\Scripts\Activate.ps1
# On Linux / macOS:
source .venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt
alembic upgrade head
```

### Step 4.3: Frontend Web Dashboard Setup (Next.js 15)
```bash
cd apps/web
npm install
npm run dev
```

---

## 5. Running the Complete Zero-Cost Stack

1. **Terminal 1 (Ollama Local Daemon):** `ollama serve` (or run in background tray)
2. **Terminal 2 (FastAPI Control Plane):** `cd apps/api && uvicorn app.main:app --reload --port 8000`
3. **Terminal 3 (Next.js Dashboard):** `cd apps/web && npm run dev`

Open [http://localhost:3000](http://localhost:3000) to access your 100% private, zero-cost AI operating system!
