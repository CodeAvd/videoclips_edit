import base64
import binascii
from collections.abc import Callable
import hashlib
import hmac
import json
import time
from typing import Annotated, Any, Literal

from fastapi import Depends, Header, Request
from pydantic import BaseModel
from starlette import status

from app.core.config import get_settings
from app.core.errors import AppError
from app.models.enums import ActorRole

SUPPORTED_AUTH_MODES = {"development_header", "session_cookie"}
TOKEN_ALGORITHM = "HS256"

class AuthContext(BaseModel):
    actor_id: str
    principal_type: Literal["user", "worker"] = "user"
    role: ActorRole | None = None
    scopes: tuple[str, ...] = ()


def validate_auth_settings() -> None:
    settings = get_settings()
    if settings.auth_mode not in SUPPORTED_AUTH_MODES:
        raise RuntimeError(f"Unsupported AUTH_MODE: {settings.auth_mode}")

    try:
        ActorRole(settings.default_dev_role)
    except ValueError as exc:
        raise RuntimeError(f"Unsupported DEFAULT_DEV_ROLE: {settings.default_dev_role}") from exc

    if settings.auth_mode == "session_cookie" and not settings.auth_session_secret:
        raise RuntimeError("AUTH_SESSION_SECRET is required when AUTH_MODE=session_cookie.")


def build_signed_auth_token(claims: dict[str, Any], secret: str) -> str:
    header = {"alg": TOKEN_ALGORITHM, "typ": "JWT"}
    encoded_header = _encode_token_segment(header)
    encoded_claims = _encode_token_segment(claims)
    signing_input = f"{encoded_header}.{encoded_claims}".encode("utf-8")
    signature = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    return f"{encoded_header}.{encoded_claims}.{_base64url_encode(signature)}"


def _base64url_encode(payload: bytes) -> str:
    return base64.urlsafe_b64encode(payload).rstrip(b"=").decode("ascii")


def _base64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(f"{value}{padding}".encode("ascii"))


def _encode_token_segment(payload: dict[str, Any]) -> str:
    return _base64url_encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))


def _decode_token_segment(value: str) -> dict[str, Any]:
    try:
        decoded = _base64url_decode(value)
        payload = json.loads(decoded.decode("utf-8"))
    except (ValueError, binascii.Error, json.JSONDecodeError) as exc:
        raise _unauthorized_error("Malformed authentication token.") from exc
    if not isinstance(payload, dict):
        raise _unauthorized_error("Malformed authentication token.")
    return payload


def _decode_signed_auth_token(token: str, *, secret: str, expected_issuer: str | None) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) != 3:
        raise _unauthorized_error("Malformed authentication token.")
    encoded_header, encoded_claims, encoded_signature = parts
    header = _decode_token_segment(encoded_header)
    if header.get("alg") != TOKEN_ALGORITHM:
        raise _unauthorized_error("Unsupported authentication token algorithm.")

    signing_input = f"{encoded_header}.{encoded_claims}".encode("utf-8")
    expected_signature = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    try:
        actual_signature = _base64url_decode(encoded_signature)
    except binascii.Error as exc:
        raise _unauthorized_error("Malformed authentication token signature.") from exc
    if not hmac.compare_digest(actual_signature, expected_signature):
        raise _unauthorized_error("Invalid authentication token signature.")

    claims = _decode_token_segment(encoded_claims)
    expires_at = claims.get("exp")
    if expires_at is not None:
        try:
            expires_at_value = int(expires_at)
        except (TypeError, ValueError) as exc:
            raise _unauthorized_error("Malformed authentication token expiry.") from exc
        if expires_at_value <= int(time.time()):
            raise _unauthorized_error("Authentication token has expired.")

    if expected_issuer is not None and claims.get("iss") != expected_issuer:
        raise _unauthorized_error("Authentication token issuer is not allowed.")

    return claims


def _parse_actor_role(role_value: Any) -> ActorRole:
    try:
        return ActorRole(str(role_value))
    except ValueError as exc:
        raise _unauthorized_error(f"Unsupported actor role: {role_value}") from exc


def _parse_actor_id(actor_id: Any, *, field_name: str) -> str:
    if not isinstance(actor_id, str) or not actor_id.strip():
        raise _unauthorized_error(f"Missing {field_name} in authentication claims.")
    return actor_id.strip()


def _parse_scopes(scope_claim: Any) -> tuple[str, ...]:
    if scope_claim is None:
        return ()
    if isinstance(scope_claim, str):
        return tuple(scope for scope in scope_claim.split() if scope)
    if isinstance(scope_claim, list) and all(isinstance(scope, str) for scope in scope_claim):
        return tuple(scope.strip() for scope in scope_claim if scope.strip())
    raise _unauthorized_error("Malformed worker scope claim.")


def _unauthorized_error(message: str) -> AppError:
    return AppError(
        code="unauthorized",
        message=message,
        http_status=status.HTTP_401_UNAUTHORIZED,
    )


def get_auth_context(
    request: Request,
    x_actor_id: Annotated[str | None, Header()] = None,
    x_actor_role: Annotated[str | None, Header()] = None,
) -> AuthContext:
    validate_auth_settings()
    settings = get_settings()

    if settings.auth_mode == "development_header":
        actor_id = (x_actor_id or settings.default_dev_actor_id).strip()
        if not actor_id:
            raise _unauthorized_error("Missing X-Actor-Id header.")
        role = _parse_actor_role(x_actor_role or settings.default_dev_role)
        return AuthContext(actor_id=actor_id, principal_type="user", role=role)

    session_token = request.cookies.get(settings.auth_session_cookie_name)
    if session_token is None or not session_token.strip():
        raise _unauthorized_error("Authentication cookie is required.")

    claims = _decode_signed_auth_token(
        session_token.strip(),
        secret=settings.auth_session_secret or "",
        expected_issuer=settings.auth_session_issuer,
    )
    if claims.get("principal_type", "user") != "user":
        raise _unauthorized_error("Authentication cookie does not represent a console user.")
    return AuthContext(
        actor_id=_parse_actor_id(claims.get("actor_id"), field_name="actor_id"),
        principal_type="user",
        role=_parse_actor_role(claims.get("role")),
    )


def get_worker_auth_context(
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> AuthContext:
    settings = get_settings()
    if not settings.auth_worker_jwt_secret:
        raise RuntimeError("AUTH_WORKER_JWT_SECRET is required for worker JWT verification.")
    if authorization is None or not authorization.startswith("Bearer "):
        raise _unauthorized_error("Bearer token is required.")

    claims = _decode_signed_auth_token(
        authorization.removeprefix("Bearer ").strip(),
        secret=settings.auth_worker_jwt_secret,
        expected_issuer=settings.auth_worker_jwt_issuer,
    )
    if claims.get("principal_type", "worker") != "worker":
        raise _unauthorized_error("Authentication token does not represent a worker principal.")
    scopes = _parse_scopes(claims.get("scope", claims.get("scopes")))
    if settings.auth_worker_required_scope not in scopes:
        raise _unauthorized_error("Worker token is missing the required scope.")
    return AuthContext(
        actor_id=_parse_actor_id(
            claims.get("worker_id", claims.get("sub", claims.get("actor_id"))),
            field_name="worker_id",
        ),
        principal_type="worker",
        scopes=scopes,
    )


def require_role(*allowed_roles: ActorRole) -> Callable[[AuthContext], AuthContext]:
    def dependency(auth: Annotated[AuthContext, Depends(get_auth_context)]) -> AuthContext:
        if auth.principal_type != "user" or auth.role not in allowed_roles:
            raise AppError(
                code="forbidden",
                message="Actor does not have access to this resource.",
                http_status=status.HTTP_403_FORBIDDEN,
            )
        return auth

    return dependency
