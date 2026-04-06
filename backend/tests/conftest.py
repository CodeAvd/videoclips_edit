import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import os
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import inspect, text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.core.database import Base, get_db_session
from app.main import app
from app.models import *  # noqa: F401,F403
from app.services.storage import get_storage_service

BACKEND_DIR = Path(__file__).resolve().parents[1]
ALEMBIC_INI_PATH = BACKEND_DIR / "alembic.ini"
ALEMBIC_SCRIPT_LOCATION = BACKEND_DIR / "alembic"
DISPOSABLE_DB_HINTS = ("test", "tests", "smoke", "tmp", "temp", "sandbox", "disposable")


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(_type, _compiler, **_kwargs) -> str:
    return "JSON"


@compiles(PGUUID, "sqlite")
def compile_uuid_sqlite(_type, _compiler, **_kwargs) -> str:
    return "CHAR(36)"


def build_alembic_config() -> Config:
    config = Config(str(ALEMBIC_INI_PATH))
    config.set_main_option("script_location", str(ALEMBIC_SCRIPT_LOCATION))
    config.set_main_option("prepend_sys_path", str(BACKEND_DIR))
    return config


def assert_disposable_postgres_url(database_url: str) -> None:
    database_name = (make_url(database_url).database or "").lower()
    if not database_name:
        raise RuntimeError("POSTGRES_TEST_DATABASE_URL must include a database name.")
    tokens = [token for token in database_name.replace("-", "_").split("_") if token]
    if not any(token in DISPOSABLE_DB_HINTS for token in tokens):
        raise RuntimeError(
            "POSTGRES_TEST_DATABASE_URL must point to an explicitly disposable test database."
        )


def upgrade_database_to_head(database_url: str) -> str:
    previous_database_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = database_url
    get_settings.cache_clear()
    try:
        config = build_alembic_config()
        head_revision = ScriptDirectory.from_config(config).get_current_head()
        command.upgrade(config, "head")
        return head_revision
    finally:
        if previous_database_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous_database_url
        get_settings.cache_clear()


async def reset_public_schema(database_url: str) -> None:
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
            await conn.execute(text("CREATE SCHEMA public"))
    finally:
        await engine.dispose()


async def assert_database_at_head(database_url: str, *, expected_head: str) -> None:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as conn:
            def verify_revision(sync_conn) -> tuple[bool, str | None, str | None]:
                has_version_table = inspect(sync_conn).has_table("alembic_version")
                version_row = None
                current_revision = None
                if has_version_table:
                    version_row = sync_conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
                    current_revision = MigrationContext.configure(sync_conn).get_current_revision()
                return has_version_table, version_row, current_revision

            has_version_table, version_row, current_revision = await conn.run_sync(verify_revision)
    finally:
        await engine.dispose()

    assert has_version_table, "alembic_version table is missing after migration."
    assert version_row == expected_head, "Database revision does not match Alembic head."
    assert current_revision == expected_head, "Migration context current revision does not match Alembic head."


@asynccontextmanager
async def client_for_session_factory(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncClient]:
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
    try:
        async with AsyncClient(transport=transport, base_url="http://testserver") as async_client:
            yield async_client
    finally:
        app.dependency_overrides.clear()


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
    async with client_for_session_factory(session_factory) as async_client:
        yield async_client


@pytest.fixture()
def postgres_test_database_url() -> str:
    database_url = os.getenv("POSTGRES_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("POSTGRES_TEST_DATABASE_URL is not set; skipping Postgres migration smoke.")
    assert_disposable_postgres_url(database_url)
    return database_url


@pytest.fixture()
async def postgres_session_factory(
    postgres_test_database_url: str,
    storage_root,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    await reset_public_schema(postgres_test_database_url)
    head_revision = await asyncio.to_thread(upgrade_database_to_head, postgres_test_database_url)
    await assert_database_at_head(postgres_test_database_url, expected_head=head_revision)

    engine = create_async_engine(postgres_test_database_url, echo=False)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    try:
        yield factory
    finally:
        await engine.dispose()
        get_storage_service.cache_clear()
        get_settings.cache_clear()


@pytest.fixture()
async def postgres_client(
    postgres_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncClient]:
    async with client_for_session_factory(postgres_session_factory) as async_client:
        yield async_client
