# Production Deployment & Operations Guide (DEPLOYMENT_GUIDE.md)
## Project Name: AURA (Autonomous Universal Reactive Agent)
**Document Version:** 9.6.0  
**Phase:** Phase 9 — Governed OS & Hardware Automation (COMPLETE & ACCEPTED) | Phase 1–9 Master Validated  
**Classification:** Enterprise Production Operations & Infrastructure  

---

## 1. Production Deployment Topology

In production, AURA is deployed across isolated network zones behind a hardened reverse proxy:

```
                                  [Public Internet]
                                         │
                                         ▼ (HTTPS 443 / TLS 1.3)
                        +---------------------------------+
                        |  Reverse Proxy (Caddy / Nginx)  |
                        +----------------+----------------+
                                         │
                 ┌───────────────────────┴───────────────────────┐
                 ▼                                               ▼
+---------------------------------+             +---------------------------------+
|  Frontend Web Cluster (Next.js) |             |  Control Plane API (FastAPI)    |
|  - 2+ Replicas (Port 3000)      |             |  - 4+ Replicas (Port 8000)      |
+---------------------------------+             +----------------+----------------+
                                                                 │
                 ┌───────────────────────────────────────────────┴────────────────┐
                 ▼                                                                ▼
+---------------------------------+                             +---------------------------------+
|  Agent Runtime & Sandboxes      |                             |  Persistence & Memory Cluster   |
|  - Ephemeral Docker / Firejail  |                             |  - PostgreSQL 16 (HA + pgvector)|
|  - Worker Queue (pg_boss/Redis) |                             |  - FastEmbed In-Process Engine  |
+---------------------------------+                             +---------------------------------+
```

---

## 2. Docker Compose Production Deployment (`docker-compose.prod.yml`)

```yaml
version: '3.8'

services:
  postgres:
    image: postgres:16-alpine
    container_name: aura_postgres
    restart: always
    environment:
      POSTGRES_DB: aura_db
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    networks:
      - aura_internal
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER} -d aura_db"]
      interval: 10s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7.2-alpine
    container_name: aura_redis
    restart: always
    command: ["redis-server", "--appendonly", "yes", "--requirepass", "${REDIS_PASSWORD}"]
    volumes:
      - redis_data:/data
    networks:
      - aura_internal

  api:
    build:
      context: ./apps/api
      dockerfile: Dockerfile.prod
    container_name: aura_api
    restart: always
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_started
    environment:
      - DATABASE_URL=postgresql+asyncpg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/aura_db
      - REDIS_URL=redis://:${REDIS_PASSWORD}@redis:6379/0
      - AURA_SECRET_KEY=${AURA_SECRET_KEY}
    networks:
      - aura_internal
      - aura_public

  web:
    build:
      context: ./apps/web
      dockerfile: Dockerfile.prod
    container_name: aura_web
    restart: always
    depends_on:
      - api
    networks:
      - aura_public

networks:
  aura_internal:
    internal: true
  aura_public:

volumes:
  postgres_data:
  redis_data:
```

---

## 3. Reverse Proxy & SSE Streaming Configuration (Nginx)

Crucial Nginx directive to prevent buffering of real-time agent token streams:

```nginx
server {
    listen 443 ssl http2;
    server_name aura.yourdomain.com;

    ssl_certificate /etc/letsencrypt/live/aura.yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/aura.yourdomain.com/privkey.pem;

    # Frontend Dashboard
    location / {
        proxy_pass http://localhost:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    # Control Plane API & Real-Time SSE Streams
    location /api/ {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        
        # CRITICAL for SSE Streaming
        proxy_http_version 1.1;
        proxy_set_header Connection '';
        proxy_buffering off;
        proxy_cache off;
        chunked_transfer_encoding off;
        proxy_read_timeout 24h;
    }
}
```

---

## 4. Production Security Hardening & Backup Checklist

* [ ] **Database Backups:** Daily automated `pg_dump` with WAL archiving shipped to encrypted S3 bucket.
* [ ] **Docker Socket Protection:** Never expose `/var/run/docker.sock` to public network; proxy Docker API via an unprivileged rootless socket.
* [ ] **Secret Encryption Key:** Store `AURA_SECRET_KEY` in AWS KMS, HashiCorp Vault, or environment vault; never commit to git.
* [ ] **Firewall (UFW):** Allow only ports 22 (SSH with key auth), 80 (HTTP redirect), and 443 (HTTPS).
* [ ] **Rate Limiting:** Enforce 120 req/min limit per IP on public API endpoints at the reverse proxy layer.

---

## 5. Windows User-Session Daemon & Tray Operations (AURA-1005 / AURA-1006)

For desktop/local workstation deployments on Windows 11 / Windows Server:

### 5.1 Daemon Supervisor CLI Commands
```powershell
# Start daemon supervisor in foreground/supervised mode
python -m app.daemon.main --start

# Query daemon supervisor health and process identity
python -m app.daemon.main --status

# Restart managed AURA backend runtime
python -m app.daemon.main --restart

# Stop running daemon supervisor cleanly
python -m app.daemon.main --stop
```

### 5.2 Controlled Autostart Management
* **Default State**: STRICTLY **OFF** by default.
* **Registry Key**: `HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run`
* **Value Name**: `AuraAgentSupervisor`
* **Privilege Level**: Current interactive user only (NO Administrator elevation, NO SYSTEM service).

```powershell
# Enable user-session autostart on Windows logon (Opt-In)
python -m app.daemon.main --autostart-enable

# Inspect truthful autostart status
python -m app.daemon.main --autostart-status

# Disable autostart and cleanly purge registry key
python -m app.daemon.main --autostart-disable
```

### 5.3 What AURA Installs vs What It Prohibits
* **Installs (when explicitly opted in)**: Unprivileged string value `AuraAgentSupervisor` under `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` pointing to `python.exe -m app.daemon.main --start`.
* **Prohibits**:
  - NO Windows Services (`services.msc` / `CreateService`).
  - NO Task Scheduler jobs (`schtasks.exe`).
  - NO Machine-wide persistence (`HKLM`).
  - NO Embedded tokens, credentials, or secrets in registry entries or command arguments.
  - NO Auto-resurrection after Emergency Kill Switch activation without explicit operator reset.

