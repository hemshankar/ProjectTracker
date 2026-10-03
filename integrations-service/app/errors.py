"""Domain exceptions and the single place they become HTTP responses."""
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class GatewayError(Exception):
    status_code = 500
    code = "gateway_error"

    def __init__(self, message: str = ""):
        super().__init__(message or self.code)
        self.message = message or self.code


class UnknownProvider(GatewayError):
    status_code, code = 404, "unknown_provider"


class UnknownAction(GatewayError):
    status_code, code = 404, "unknown_action"


class ProviderDisabled(GatewayError):
    status_code, code = 403, "provider_disabled"


class NotConnected(GatewayError):
    status_code, code = 409, "not_connected"


class RateLimited(GatewayError):
    status_code, code = 429, "rate_limited"


class BackendUnavailable(GatewayError):
    status_code, code = 503, "backend_unavailable"


class ActionFailed(GatewayError):
    status_code, code = 502, "action_failed"


class UnknownToken(GatewayError):
    status_code, code = 404, "unknown_token"


class Unauthorized(GatewayError):
    status_code, code = 401, "unauthorized"


class Forbidden(GatewayError):
    status_code, code = 403, "forbidden"


class TooManyAttempts(GatewayError):
    status_code, code = 429, "too_many_attempts"


class Conflict(GatewayError):
    """409 with structured detail (e.g. connectionsAffected) for confirm flows."""

    status_code, code = 409, "confirmation_required"

    def __init__(self, message: str = "", detail: dict = None):
        super().__init__(message)
        self.detail = detail or {}


class InvalidInput(GatewayError):
    status_code, code = 422, "invalid_input"


class ConfigError(GatewayError):
    status_code, code = 503, "not_configured"


class InvalidWebhook(GatewayError):
    status_code, code = 401, "invalid_webhook"


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(GatewayError)
    async def _handle(_: Request, exc: GatewayError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"ok": False, "error": {"code": exc.code, "message": exc.message,
                                            **({"detail": exc.detail} if getattr(exc, "detail", None) else {})}},
        )
