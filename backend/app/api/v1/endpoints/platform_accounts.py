from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.api.deps import DbSession
from app.core.errors import AppError
from app.core.security import require_role
from app.models.config import BrandProfile, PlatformAccount
from app.models.enums import ActorRole
from app.schemas.common import ListResponse
from app.schemas.platform_account import PlatformAccountCreate, PlatformAccountOut, PlatformAccountPatch

router = APIRouter()


@router.get(
    "",
    response_model=ListResponse[PlatformAccountOut],
    dependencies=[Depends(require_role(ActorRole.viewer, ActorRole.reviewer, ActorRole.operator, ActorRole.admin))],
)
async def list_platform_accounts(db: DbSession) -> ListResponse[PlatformAccountOut]:
    result = await db.execute(select(PlatformAccount).order_by(PlatformAccount.created_at.desc()))
    items = [PlatformAccountOut.model_validate(item) for item in result.scalars().all()]
    return ListResponse(items=items, next_cursor=None)


@router.post("", response_model=PlatformAccountOut, dependencies=[Depends(require_role(ActorRole.admin))])
async def create_platform_account(payload: PlatformAccountCreate, db: DbSession) -> PlatformAccountOut:
    brand_profile = await db.get(BrandProfile, payload.brand_profile_id)
    if brand_profile is None:
        raise AppError(code="not_found", message="Brand profile not found.", http_status=404)
    platform_account = PlatformAccount(
        brand_profile_id=payload.brand_profile_id,
        platform=payload.platform,
        channel_name=payload.channel_name,
        connection_ref=f"conn::{payload.platform.value}::{payload.channel_name}",
        capabilities_jsonb=payload.capabilities_json,
    )
    db.add(platform_account)
    await db.flush()
    await db.refresh(platform_account)
    return PlatformAccountOut.model_validate(platform_account)


@router.get(
    "/{platform_account_id}",
    response_model=PlatformAccountOut,
    dependencies=[Depends(require_role(ActorRole.viewer, ActorRole.reviewer, ActorRole.operator, ActorRole.admin))],
)
async def get_platform_account(platform_account_id: UUID, db: DbSession) -> PlatformAccountOut:
    platform_account = await db.get(PlatformAccount, platform_account_id)
    if platform_account is None:
        raise AppError(code="not_found", message="Platform account not found.", http_status=404)
    return PlatformAccountOut.model_validate(platform_account)


@router.patch("/{platform_account_id}", response_model=PlatformAccountOut, dependencies=[Depends(require_role(ActorRole.admin))])
async def patch_platform_account(platform_account_id: UUID, payload: PlatformAccountPatch, db: DbSession) -> PlatformAccountOut:
    platform_account = await db.get(PlatformAccount, platform_account_id)
    if platform_account is None:
        raise AppError(code="not_found", message="Platform account not found.", http_status=404)
    patch_data = payload.model_dump(exclude_unset=True)
    if "capabilities_json" in patch_data:
        patch_data["capabilities_jsonb"] = patch_data.pop("capabilities_json")
    for field, value in patch_data.items():
        setattr(platform_account, field, value)
    await db.flush()
    await db.refresh(platform_account)
    return PlatformAccountOut.model_validate(platform_account)
