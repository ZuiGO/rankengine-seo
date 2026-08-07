class ServiceError(Exception):
    """Raised when an external service (SE Ranking, SERP API, Groq, ...) fails."""

    def __init__(
        self,
        service: str,
        message: str,
        status_code: int | None = None,
        hint: str | None = None,
    ):
        self.service = service
        self.message = message
        self.status_code = status_code
        self.hint = hint
        super().__init__(f"{service}: {message}")


def service_error_payload(exc: Exception, service: str = "service") -> dict:
    if isinstance(exc, ServiceError):
        return {
            "status": "error",
            "source": exc.service,
            "error": exc.message,
            "error_code": exc.status_code,
            "hint": exc.hint,
        }
    return {
        "status": "error",
        "source": service,
        "error": str(exc)[:300],
        "error_code": None,
        "hint": None,
    }
