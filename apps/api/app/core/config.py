"""Application configuration module using Pydantic Settings."""

import json
from typing import List, Optional, Union
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """AURA Control Plane Configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Environment
    AURA_ENV: str = Field(default="development", description="Environment: development, testing, production")
    # Security & JWT
    AURA_SECRET_KEY: str = Field(
        default="aura_default_insecure_secret_key_change_in_production_0123456789abcdef",
        description="Master encryption & JWT signing secret key",
    )
    AURA_MASTER_ENCRYPTION_KEY: str = Field(
        default="aura_32_byte_master_encryption_key_abcdef12",
        description="AES-256 master key for BYOK credential encryption",
    )
    JWT_ALGORITHM: str = Field(default="HS256", description="JWT signing algorithm")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=30, description="Access token expiration in minutes")
    REFRESH_TOKEN_EXPIRE_DAYS: int = Field(default=7, description="Refresh token expiration in days")
    AURA_API_PORT: int = Field(default=8000, description="FastAPI server port")
    AURA_LOG_LEVEL: str = Field(default="INFO", description="Logging level")

    # Database
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/aura_db",
        description="Async PostgreSQL connection URL",
    )
    DATABASE_POOL_SIZE: int = Field(default=10, description="Connection pool size")
    DATABASE_MAX_OVERFLOW: int = Field(default=20, description="Max overflow connections")

    # Local Ollama Runtime & Model Engine
    OLLAMA_BASE_URL: str = Field(default="http://localhost:11434", description="Base URL for local Ollama daemon")
    LOCAL_MODEL_GENERAL: str = Field(default="qwen2.5:7b-instruct-q4_K_M", description="Primary tool-calling model")
    LOCAL_MODEL_FAST: str = Field(default="llama3.2:3b-instruct-q4_K_M", description="Fast extraction model")
    LOCAL_MODEL_EMBEDDING: str = Field(default="BAAI/bge-base-en-v1.5", description="Local embedding model")
    OLLAMA_TIMEOUT_SECONDS: float = Field(default=120.0, description="Timeout for local LLM generation")

    # FastEmbed & Local Memory
    FASTEMBED_MODEL_NAME: str = Field(
        default="BAAI/bge-base-en-v1.5", description="Local FastEmbed model"
    )
    EMBEDDING_DIMENSION: int = Field(default=768, description="Expected vector embedding dimension")

    # Optional BYOK Cloud Keys (Local developer environment override)
    GEMINI_API_KEY: Optional[str] = Field(default=None, description="Optional Google Gemini API Key for BYOK")

    # Model Provider Routing
    DEFAULT_ROUTING_MODE: str = Field(default="local_only", description="Default routing mode: local_only, byok_only, auto")

    # Execution Sandbox & Hardening (AURA-501)
    SANDBOX_ENABLED: bool = Field(default=True, description="Enforce container sandbox isolation for code/shell tools")
    SANDBOX_RUNTIME: str = Field(default="docker", description="Container runtime: docker, wsl2, none")
    SANDBOX_DEFAULT_IMAGE: str = Field(default="python:3.12-slim", description="Default sandbox container image")
    SANDBOX_MAX_MEMORY_MB: int = Field(default=512, description="Max container memory in MB")
    SANDBOX_MAX_CPU_PERCENT: int = Field(default=100, description="Max CPU quota (100% = 1 core)")
    SANDBOX_TIMEOUT_SECONDS: int = Field(default=60, description="Max execution timeout in sandbox")
    WORKSPACE_ROOT_DIR: str = Field(default="./workspaces", description="Root directory for workspace isolation")
    SSRF_PROTECTION_ENABLED: bool = Field(default=True, description="Enforce strict SSRF protection on network tools")

    # Local OpenTelemetry Distributed Tracing (AURA-505)
    OTEL_ENABLED: bool = Field(default=True, description="Enable local OpenTelemetry tracing")
    OTEL_SERVICE_NAME: str = Field(default="aura-control-plane", description="OpenTelemetry service name")
    OTEL_EXPORTER_TYPE: str = Field(default="in_memory", description="OTel exporter type: in_memory, console, otlp, none")
    OTEL_OTLP_ENDPOINT: str = Field(default="http://localhost:4317", description="Local OTLP collector endpoint")
    OTEL_MAX_ATTR_LENGTH: int = Field(default=256, description="Max length for string span attributes")

    # CORS
    CORS_ORIGINS: Union[str, List[str]] = Field(
        default=["http://localhost:3000", "http://127.0.0.1:3000"],
        description="Allowed CORS origins",
    )

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> List[str]:
        if isinstance(v, str):
            if v.startswith("[") and v.endswith("]"):
                try:
                    return json.loads(v)
                except Exception:
                    pass
            return [i.strip() for i in v.split(",") if i.strip()]
        elif isinstance(v, list):
            return v
    # Phase 7: Real-Time Local Voice & Speech
    VOICE_STT_MODEL: str = Field(default="base.en", description="Faster-Whisper model: base.en, small.en")
    VOICE_STT_DEVICE: str = Field(default="cpu", description="STT execution device: cpu, cuda")
    VOICE_STT_COMPUTE_TYPE: str = Field(default="int8", description="STT quantization type: int8, float16, float32")
    VOICE_VAD_THRESHOLD: float = Field(default=0.5, description="Silero VAD speech detection probability threshold")
    VOICE_VAD_HANGOVER_MS: int = Field(default=300, description="VAD speech hangover buffer in milliseconds")
    VOICE_TTS_MODEL: str = Field(default="en_US-lessac-medium", description="Piper-TTS ONNX model name")
    VOICE_TICKET_EXPIRE_SECONDS: int = Field(default=60, description="Short-lived voice WebSocket ticket TTL in seconds")
    MODELS_CACHE_DIR: str = Field(default="./.cache/aura/models", description="Root cache directory for local open weights models")

    @property
    def is_production(self) -> bool:
        return self.AURA_ENV.lower() == "production"

    @property
    def is_testing(self) -> bool:
        return self.AURA_ENV.lower() == "testing"


settings = Settings()
