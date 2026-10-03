"""Standardized error models and exception classes for AURA."""

from datetime import datetime, timezone
from typing import Any, Dict, Optional
from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: Optional[Dict[str, Any]] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    success: bool = False
    error: ErrorDetail
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    request_id: Optional[str] = None


class AuraException(Exception):
    """Base exception for all AURA domain errors."""

    def __init__(
        self,
        message: str,
        code: str = "INTERNAL_ERROR",
        status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details or {}


class DatabaseError(AuraException):
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            code="DATABASE_ERROR",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            details=details,
        )


class LocalModelUnavailableError(AuraException):
    def __init__(self, message: str = "Local Ollama runtime is unavailable", details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            code="LOCAL_MODEL_UNAVAILABLE",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            details=details,
        )


class ModelTimeoutError(AuraException):
    def __init__(self, message: str = "Local model execution timed out", details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            code="MODEL_TIMEOUT",
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            details=details,
        )


class ResourceNotFoundError(AuraException):
    def __init__(self, resource: str = "Resource", identifier: Any = ""):
        super().__init__(
            message=f"{resource} with identifier '{identifier}' was not found.",
            code="RESOURCE_NOT_FOUND",
            status_code=status.HTTP_404_NOT_FOUND,
        )


class EntityNotFoundError(ResourceNotFoundError):
    """Alias for ResourceNotFoundError."""
    def __init__(self, resource: str = "Entity", identifier: Any = ""):
        super().__init__(resource=resource, identifier=identifier)


class AuthenticationError(AuraException):
    def __init__(self, message: str = "Authentication failed", details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            code="AUTHENTICATION_ERROR",
            status_code=status.HTTP_401_UNAUTHORIZED,
            details=details,
        )


class AuthorizationError(AuraException):
    def __init__(self, message: str = "Access denied", details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            code="AUTHORIZATION_ERROR",
            status_code=status.HTTP_403_FORBIDDEN,
            details=details,
        )


class ConflictError(AuraException):
    def __init__(self, message: str = "Resource conflict", details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            code="CONFLICT_ERROR",
            status_code=status.HTTP_409_CONFLICT,
            details=details,
        )


class OperationInProgressError(AuraException):
    def __init__(self, message: str = "An active background job is already in progress for this resource", details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            code="OPERATION_ALREADY_IN_PROGRESS",
            status_code=status.HTTP_409_CONFLICT,
            details=details,
        )


class OllamaUnavailableError(LocalModelUnavailableError):
    """Alias for LocalModelUnavailableError."""
    pass


class ModelUnavailableError(AuraException):
    def __init__(self, message: str = "Model provider is unavailable", details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            code="MODEL_UNAVAILABLE",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            details=details,
        )


class RateLimitError(AuraException):
    def __init__(self, message: str = "Rate limit or quota exceeded", details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            code="RATE_LIMIT_EXCEEDED",
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            details=details,
        )


class SandboxExecutionError(AuraException):
    def __init__(self, message: str = "Sandbox execution failed", details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            code="SANDBOX_EXECUTION_ERROR",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            details=details,
        )


class ValidationError(AuraException):
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            code="VALIDATION_ERROR",
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            details=details,
        )


class EmbeddingModelUnavailableError(AuraException):
    def __init__(self, message: str = "Local FastEmbed embedding model is unavailable", details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            code="EMBEDDING_MODEL_UNAVAILABLE",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            details=details,
        )


class EmbeddingDimensionMismatchError(AuraException):
    def __init__(self, message: str = "Embedding vector dimension mismatch", details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            code="EMBEDDING_DIMENSION_MISMATCH",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            details=details,
        )


class ModelNotFoundError(AuraException):
    def __init__(self, model_name: str, path_or_hint: str = "", details: Optional[Dict[str, Any]] = None):
        msg = f"Required local model '{model_name}' was not found at '{path_or_hint}'. Zero-cost local execution requires local model assets."
        super().__init__(
            message=msg,
            code="MODEL_NOT_FOUND",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            details=details or {"model_name": model_name, "path_or_hint": path_or_hint},
        )


class VoiceProcessingError(AuraException):
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            code="VOICE_PROCESSING_ERROR",
            status_code=status.HTTP_400_BAD_REQUEST,
            details=details,
        )


async def aura_exception_handler(request: Request, exc: AuraException) -> JSONResponse:
    from app.core.logging import get_correlation_id

    error_response = ErrorResponse(
        error=ErrorDetail(code=exc.code, message=exc.message, details=exc.details),
        request_id=get_correlation_id(),
    )
    return JSONResponse(status_code=exc.status_code, content=error_response.model_dump())


async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    from app.core.config import settings
    from app.core.logging import get_correlation_id, logger

    req_id = get_correlation_id()
    logger.exception(f"Unhandled server exception [req_id={req_id}]: {str(exc)}")

    message = str(exc) if not settings.is_production else "An internal server error occurred."
    error_response = ErrorResponse(
        error=ErrorDetail(code="INTERNAL_SERVER_ERROR", message=message),
        request_id=req_id,
    )
    return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content=error_response.model_dump())
