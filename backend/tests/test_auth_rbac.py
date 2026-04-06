import pytest

from app.core.errors import AppError
from app.core.security import get_worker_auth_context, validate_auth_settings
from conftest import client_for_session_factory


async def test_development_header_mode_still_authorizes_protected_routes(client, actor_headers) -> None:
    response = await client.get("/api/v1/jobs", headers=actor_headers)

    assert response.status_code == 200


async def test_session_cookie_mode_requires_cookie(session_factory, configure_auth) -> None:
    configure_auth(
        AUTH_MODE="session_cookie",
        AUTH_SESSION_SECRET="test-session-secret",
        AUTH_SESSION_COOKIE_NAME="test_session",
        AUTH_SESSION_ISSUER="test-suite",
    )

    async with client_for_session_factory(session_factory) as client:
        response = await client.get("/api/v1/jobs")

    assert response.status_code == 401
    assert response.json()["code"] == "unauthorized"


async def test_session_cookie_mode_rejects_bad_signature(session_factory, configure_auth, session_cookie_factory) -> None:
    configure_auth(
        AUTH_MODE="session_cookie",
        AUTH_SESSION_SECRET="test-session-secret",
        AUTH_SESSION_COOKIE_NAME="test_session",
        AUTH_SESSION_ISSUER="test-suite",
    )
    cookie = session_cookie_factory(actor_id="cookie-admin", role="admin")
    cookie_name, cookie_value = next(iter(cookie.items()))

    async with client_for_session_factory(session_factory) as client:
        client.cookies.set(cookie_name, f"{cookie_value}tampered")
        response = await client.get("/api/v1/jobs")

    assert response.status_code == 401
    assert response.json()["code"] == "unauthorized"


async def test_session_cookie_mode_rejects_invalid_role_claim(session_factory, configure_auth, session_cookie_factory) -> None:
    configure_auth(
        AUTH_MODE="session_cookie",
        AUTH_SESSION_SECRET="test-session-secret",
        AUTH_SESSION_COOKIE_NAME="test_session",
        AUTH_SESSION_ISSUER="test-suite",
    )
    cookie = session_cookie_factory(actor_id="cookie-admin", role="ghost")

    async with client_for_session_factory(session_factory) as client:
        client.cookies.update(cookie)
        response = await client.get("/api/v1/jobs")

    assert response.status_code == 401
    assert response.json()["code"] == "unauthorized"


async def test_session_cookie_mode_forbids_underprivileged_writes(session_factory, configure_auth, session_cookie_factory) -> None:
    configure_auth(
        AUTH_MODE="session_cookie",
        AUTH_SESSION_SECRET="test-session-secret",
        AUTH_SESSION_COOKIE_NAME="test_session",
        AUTH_SESSION_ISSUER="test-suite",
    )
    viewer_cookie = session_cookie_factory(actor_id="viewer-1", role="viewer")

    async with client_for_session_factory(session_factory) as client:
        client.cookies.update(viewer_cookie)
        response = await client.post(
            "/api/v1/uploads",
            json={
                "filename": "clip.mp4",
                "content_type": "video/mp4",
                "size_bytes": 128,
            },
        )

    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


async def test_session_cookie_mode_allows_admin_write_and_reviewer_read(
    session_factory,
    configure_auth,
    session_cookie_factory,
) -> None:
    configure_auth(
        AUTH_MODE="session_cookie",
        AUTH_SESSION_SECRET="test-session-secret",
        AUTH_SESSION_COOKIE_NAME="test_session",
        AUTH_SESSION_ISSUER="test-suite",
    )
    admin_cookie = session_cookie_factory(actor_id="admin-1", role="admin")
    reviewer_cookie = session_cookie_factory(actor_id="reviewer-1", role="reviewer")

    async with client_for_session_factory(session_factory) as client:
        client.cookies.update(admin_cookie)
        create_response = await client.post(
            "/api/v1/uploads",
            json={
                "filename": "clip.mp4",
                "content_type": "video/mp4",
                "size_bytes": 128,
            },
        )
        assert create_response.status_code == 200

        client.cookies.clear()
        client.cookies.update(reviewer_cookie)
        read_response = await client.get(f"/api/v1/uploads/{create_response.json()['id']}")

    assert read_response.status_code == 200


def test_worker_jwt_dependency_accepts_valid_worker_token(configure_auth, worker_jwt_factory) -> None:
    configure_auth(
        AUTH_WORKER_JWT_SECRET="worker-secret",
        AUTH_WORKER_JWT_ISSUER="worker-suite",
        AUTH_WORKER_REQUIRED_SCOPE="worker:internal",
    )
    token = worker_jwt_factory(worker_id="worker-42")

    auth = get_worker_auth_context(authorization=f"Bearer {token}")

    assert auth.principal_type == "worker"
    assert auth.actor_id == "worker-42"
    assert auth.scopes == ("worker:internal",)


def test_worker_jwt_dependency_rejects_console_principal(configure_auth, worker_jwt_factory) -> None:
    configure_auth(
        AUTH_WORKER_JWT_SECRET="worker-secret",
        AUTH_WORKER_JWT_ISSUER="worker-suite",
        AUTH_WORKER_REQUIRED_SCOPE="worker:internal",
    )
    token = worker_jwt_factory(worker_id="worker-42", principal_type="user")

    with pytest.raises(AppError) as exc_info:
        get_worker_auth_context(authorization=f"Bearer {token}")

    assert exc_info.value.http_status == 401
    assert exc_info.value.code == "unauthorized"


def test_validate_auth_settings_rejects_missing_session_secret(configure_auth) -> None:
    configure_auth(
        AUTH_MODE="session_cookie",
        AUTH_SESSION_SECRET=None,
    )

    with pytest.raises(RuntimeError, match="AUTH_SESSION_SECRET"):
        validate_auth_settings()
