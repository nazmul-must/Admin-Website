"""Records every request a signed-in employee makes (see AccessLog)."""

from collections.abc import Callable

from django.http import HttpRequest, HttpResponse

from .models import AccessLog

# Static files and probes are not page views. The emailed sign-in link holds a one-time token.
NOT_LOGGED = ("/static/", "/health/", "/employees/verify/")
MAX_PATH = 2000


class AccessLogMiddleware:
    """Writes one AccessLog row per request by a signed-in employee, after the response."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        """Standard Django middleware constructor."""
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        """Run the request, then record it if an employee is signed in."""
        response = self.get_response(request)
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated and not request.path.startswith(NOT_LOGGED):
            AccessLog.objects.create(
                employee=user,
                email=user.email or user.get_username(),
                method=request.method or "",
                path=request.get_full_path()[:MAX_PATH],
                status=response.status_code,
            )
        return response
