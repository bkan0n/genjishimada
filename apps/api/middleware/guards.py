from litestar.connection import ASGIConnection
from litestar.exceptions import NotAuthorizedException
from litestar.handlers import BaseRouteHandler

from middleware.auth import AuthToken


def scope_guard(connection: ASGIConnection, route_handler: BaseRouteHandler) -> None:
    if route_handler.opt.get("exclude_from_auth"):
        return

    auth: AuthToken = connection.auth

    if auth.is_superuser:
        return

    required_scopes: set[str] | None = route_handler.opt.get("required_scopes")

    if not required_scopes:
        raise NotAuthorizedException(detail="This endpoint requires elevated privileges")

    token_scopes = set(auth.scopes)
    missing = required_scopes - token_scopes

    if missing:
        raise NotAuthorizedException(detail=f"Missing required scopes: {', '.join(sorted(missing))}")
