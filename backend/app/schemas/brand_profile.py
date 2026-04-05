from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import AppSchema


class BrandProfileCreate(BaseModel):
    name: str
    language: str
    caption_style_defaults: dict[str, Any] = Field(default_factory=dict)
    overlay_policy: dict[str, Any] = Field(default_factory=dict)
    music_policy: dict[str, Any] = Field(default_factory=dict)
    platform_defaults: dict[str, Any] = Field(default_factory=dict)


class BrandProfilePatch(BaseModel):
    caption_style_defaults: dict[str, Any] | None = None
    overlay_policy: dict[str, Any] | None = None
    music_policy: dict[str, Any] | None = None
    platform_defaults: dict[str, Any] | None = None


class BrandProfileOut(AppSchema):
    id: UUID
    name: str
    language: str
    caption_style_defaults: dict[str, Any]
    overlay_policy: dict[str, Any]
    music_policy: dict[str, Any]
    platform_defaults: dict[str, Any]
