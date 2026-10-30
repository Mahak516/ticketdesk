"""Domain exceptions. Each carries the HTTP status the API should answer with."""


class AppError(Exception):
    """Base class for all expected, business-level errors."""

    status_code = 500
    code = "internal_error"

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class DuplicateError(AppError):
    status_code = 409
    code = "duplicate"


class InvalidTransitionError(AppError):
    status_code = 409
    code = "invalid_transition"
