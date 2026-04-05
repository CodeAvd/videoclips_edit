from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.core.database import Base, get_db_session
from app.main import app
from app.models import *  # noqa: F401,F403
from app.services.storage import get_storage_service


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(_type, _compiler, **_kwargs) -> str:
    return "JSON"


@compiles(PGUUID, "sqlite")
def compile_uuid_sqlite(_type, _compiler, **_kwargs) -> str:
    return "CHAR(36)"


@pytest.fixture()
def actor_headers() -> dict[str, str]:
    return {
        "X-Actor-Id": "test-admin",
        "X-Actor-Role": "admin",
    }


@pytest.fixture()
def storage_root(tmp_path, monkeypatch) -> str:
    root = tmp_path / "storage"
    monkeypatch.setenv("APP_BASE_URL", "http://testserver")
    monkeypatch.setenv("LOCAL_STORAGE_DIR", str(root))
    monkeypatch.setenv("ASR_PROVIDER_PRIMARY", "stub")
    monkeypatch.setenv("ASR_PROVIDER_FALLBACK", "")
    get_settings.cache_clear()
    get_storage_service.cache_clear()
    return str(root)


@pytest.fixture()
async def session_factory(storage_root) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    try:
        yield factory
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await engine.dispose()
        get_storage_service.cache_clear()
        get_settings.cache_clear()


@pytest.fixture()
async def client(session_factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncClient]:
    async def override_db() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db_session] = override_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as async_client:
        yield async_client
    app.dependency_overrides.clear()
