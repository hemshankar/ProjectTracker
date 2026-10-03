"""Domain exceptions and the single place they become HTTP responses."""
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class AccountingError(Exception):
    status_code = 500
    code = "accounting_error"

    def __init__(self, message: str = ""):
        super().__init__(message or self.code)
        self.message = message or self.code


class UnsupportedSchemaVersion(AccountingError):
    status_code, code = 400, "unsupported_schema_version"


class BatchTooLarge(AccountingError):
    status_code, code = 400, "batch_too_large"


class InvalidQuery(AccountingError):
    status_code, code = 400, "invalid_query"


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AccountingError)
    async def _handle(_: Request, exc: AccountingError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"ok": False, "error": {"code": exc.code, "message": exc.message}},
        )
