from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.enums import Platform, PlatformAccountStatus
from app.schemas.common import AppSchema


class PlatformAccountCreate(BaseModel):
    brand_profile_id: UUID
    platform: Platform
    channel_name: str
    credential_payload: dict[str, Any] = Field(default_factory=dict)
    capabilities_json: dict[str, Any] = Field(default_factory=dict)


class PlatformAccountPatch(BaseModel):
    channel_name: str | None = None
    capabilities_json: dict[str, Any] | None = None
    status: PlatformAccountStatus | None = None


class PlatformAccountOut(AppSchema):
    id: UUID
    brand_profile_id: UUID
    platform: Platform
    channel_name: str
    connection_ref: str
    capabilities_jsonb: dict[str, Any]
    status: PlatformAccountStatus
