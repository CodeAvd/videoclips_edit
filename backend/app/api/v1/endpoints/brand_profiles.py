from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.api.deps import DbSession
from app.core.errors import AppError
from app.core.security import require_role
from app.models.config import BrandProfile
from app.models.enums import ActorRole
from app.schemas.brand_profile import BrandProfileCreate, BrandProfileOut, BrandProfilePatch
from app.schemas.common import ListResponse

router = APIRouter()


@router.get("", response_model=ListResponse[BrandProfileOut], dependencies=[Depends(require_role(ActorRole.viewer, ActorRole.reviewer, ActorRole.operator, ActorRole.admin))])
async def list_brand_profiles(db: DbSession) -> ListResponse[BrandProfileOut]:
    result = await db.execute(select(BrandProfile).order_by(BrandProfile.created_at.desc()))
    items = [BrandProfileOut.model_validate(item) for item in result.scalars().all()]
    return ListResponse(items=items, next_cursor=None)


@router.post("", response_model=BrandProfileOut, dependencies=[Depends(require_role(ActorRole.admin))])
async def create_brand_profile(payload: BrandProfileCreate, db: DbSession) -> BrandProfileOut:
    profile = BrandProfile(**payload.model_dump())
    db.add(profile)
    await db.flush()
    await db.refresh(profile)
    return BrandProfileOut.model_validate(profile)


@router.get("/{brand_profile_id}", response_model=BrandProfileOut, dependencies=[Depends(require_role(ActorRole.viewer, ActorRole.reviewer, ActorRole.operator, ActorRole.admin))])
async def get_brand_profile(brand_profile_id: UUID, db: DbSession) -> BrandProfileOut:
    profile = await db.get(BrandProfile, brand_profile_id)
    if profile is None:
        raise AppError(code="not_found", message="Brand profile not found.", http_status=404)
    return BrandProfileOut.model_validate(profile)


@router.patch("/{brand_profile_id}", response_model=BrandProfileOut, dependencies=[Depends(require_role(ActorRole.admin))])
async def patch_brand_profile(brand_profile_id: UUID, payload: BrandProfilePatch, db: DbSession) -> BrandProfileOut:
    profile = await db.get(BrandProfile, brand_profile_id)
    if profile is None:
        raise AppError(code="not_found", message="Brand profile not found.", http_status=404)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(profile, field, value)
    await db.flush()
    await db.refresh(profile)
    return BrandProfileOut.model_validate(profile)
