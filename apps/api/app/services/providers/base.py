"""Abstract Base Class and Data Contracts for Provider-Neutral Model Interface."""

from abc import ABC, abstractmethod
from typing import Any, AsyncGenerator, Dict, List, Optional
from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    """Normalized chat message."""
    role: str = Field(description="Role: system, user, assistant, tool")
    content: str = Field(description="Text content")
    name: Optional[str] = None


class ChatRequest(BaseModel):
    """Normalized chat generation request."""
    model: str
    messages: List[ChatMessage]
    temperature: float = 0.7
    max_tokens: Optional[int] = None
    stream: bool = False
    json_mode: bool = False


class ChatResponse(BaseModel):
    """Normalized chat generation response."""
    model: str
    content: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    finish_reason: str = "stop"
    provider: str = "local"


class ModelInfo(BaseModel):
    """Information about an available model."""
    id: str
    name: str
    provider: str
    context_window: int = 32768
    is_local: bool = True
    billing_tier: str = "zero_cost_local"


class ProviderHealthStatus(BaseModel):
    """Status probe result for a model provider."""
    provider_type: str
    is_available: bool
    status: str  # healthy, degraded, unavailable, invalid_credentials
    message: str
    available_models: List[str] = []
    error_category: Optional[str] = None


class ModelProvider(ABC):
    """Abstract interface that all model backends (Ollama, Gemini BYOK, OpenAI) must implement."""

    @abstractmethod
    async def generate_chat(self, request: ChatRequest) -> ChatResponse:
        """Generate full completion response."""
        pass

    @abstractmethod
    async def generate_stream(self, request: ChatRequest) -> AsyncGenerator[str, None]:
        """Stream response tokens as an async generator."""
        pass

    @abstractmethod
    async def generate_structured(self, request: ChatRequest, response_model: Any) -> Any:
        """Generate structured response validated against a Pydantic model."""
        pass

    @abstractmethod
    async def validate_credentials(self) -> bool:
        """Validate whether the provider credentials are valid and active."""
        pass

    @abstractmethod
    async def health_check(self) -> ProviderHealthStatus:
        """Probe provider health and return status."""
        pass

    @abstractmethod
    async def list_models(self) -> List[ModelInfo]:
        """List models available on this provider."""
        pass
