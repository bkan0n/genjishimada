from litestar.connection import ASGIConnection
from litestar.exceptions import NotAuthorizedException
from litestar.handlers import BaseRouteHandler

from middleware.auth import AuthToken

AUTH_EXCLUDED_PATHS = frozenset({"/docs", "/schema", "/healthcheck"})


def scope_guard(connection: ASGIConnection, route_handler: BaseRouteHandler) -> None:
    """Check if the request is authenticated."""
    if route_handler.opt.get("exclude_from_auth", False):
        return

    request_path = connection.scope.get("path", "")
    if request_path in AUTH_EXCLUDED_PATHS or request_path.startswith("/docs"):
        return

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
