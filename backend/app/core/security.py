from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Header
from pydantic import BaseModel
from starlette import status

from app.core.config import get_settings
from app.core.errors import AppError
from app.models.enums import ActorRole

settings = get_settings()


class AuthContext(BaseModel):
    actor_id: str
    role: ActorRole


def get_auth_context(
    x_actor_id: Annotated[str | None, Header()] = None,
    x_actor_role: Annotated[str | None, Header()] = None,
) -> AuthContext:
    if settings.auth_mode != "development_header":
        raise AppError(
            code="forbidden",
            message="Configured auth mode is not implemented yet.",
            http_status=status.HTTP_501_NOT_IMPLEMENTED,
        )

    actor_id = x_actor_id or settings.default_dev_actor_id
    role_value = x_actor_role or settings.default_dev_role
    try:
        role = ActorRole(role_value)
    except ValueError as exc:
        raise AppError(
            code="forbidden",
            message=f"Unsupported actor role: {role_value}",
            http_status=status.HTTP_403_FORBIDDEN,
        ) from exc

    return AuthContext(actor_id=actor_id, role=role)


def require_role(*allowed_roles: ActorRole) -> Callable[[AuthContext], AuthContext]:
    def dependency(auth: Annotated[AuthContext, Depends(get_auth_context)]) -> AuthContext:
        if auth.role not in allowed_roles:
            raise AppError(
                code="forbidden",
                message="Actor does not have access to this resource.",
                http_status=status.HTTP_403_FORBIDDEN,
            )
        return auth

    return dependency
