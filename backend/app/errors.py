"""Structured API errors: {"error": {"code", "message", "details"}}."""


class ApiError(Exception):
    def __init__(self, code: str, message: str, status: int = 400, details: dict | None = None):
        self.code = code
        self.message = message
        self.status = status
        self.details = details or {}
        super().__init__(message)


# Canonical error codes used across the app:
#   DOCKER_UNAVAILABLE, IMAGE_MISSING, CONTAINER_EXISTS, CONTAINER_NOT_RUNNING,
#   CONTAINER_NOT_FOUND, CLI_MISSING, LOGIN_FAILED, AUTH_EXPIRED, AUTH_TIMEOUT,
#   DEVICE_CODE_EXPIRED, PTY_CRASHED, PARSE_FAILED, RESOURCE_LIMIT,
#   NETWORK_UNAVAILABLE, VOLUME_PERMISSION, UNSUPPORTED_PROVIDER,
#   ACCOUNT_NOT_FOUND, SESSION_NOT_FOUND, NAME_TAKEN, INVALID_NAME


async def api_error_handler(_, exc: ApiError):
    from fastapi.responses import JSONResponse

    return JSONResponse(
        status_code=exc.status,
        content={"error": {"code": exc.code, "message": exc.message, "details": exc.details}},
    )
