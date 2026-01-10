from litestar.connection import ASGIConnection
from litestar.exceptions import NotAuthorizedException
from litestar.handlers import BaseRouteHandler

from middleware.auth import AuthToken

# Paths that should skip authentication entirely
# Must match the exclude list in the auth middleware (app.py)
AUTH_EXCLUDED_PATHS = frozenset({"/docs", "/schema", "/healthcheck"})


def scope_guard(connection: ASGIConnection, route_handler: BaseRouteHandler) -> None:
    # Skip if route is explicitly excluded from auth via opt
    if route_handler.opt.get("exclude_from_auth", False):
        return

    # Skip if path is in the excluded paths list
    # This handles OpenAPI docs and other public routes
    request_path = connection.scope.get("path", "")
    if request_path in AUTH_EXCLUDED_PATHS or request_path.startswith("/docs"):
        return

    # Check if auth was set by the auth middleware
    auth_data = connection.scope.get("auth")
    if auth_data is None:
        raise NotAuthorizedException(detail="Authentication required")

    auth: AuthToken = auth_data

    if auth.is_superuser:
        return

    required_scopes: set[str] | None = route_handler.opt.get("required_scopes")

    if not required_scopes:
        raise NotAuthorizedException(detail="This endpoint requires elevated privileges")

    token_scopes = set(auth.scopes)
    missing = required_scopes - token_scopes

    if missing:
        raise NotAuthorizedException(detail=f"Missing required scopes: {', '.join(sorted(missing))}")
