from uuid import UUID

from sqlalchemy import Enum, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID as PGUUID

from app.models.base import BaseModel, CreatedAtMixin, UpdatedAtMixin, UuidPrimaryKeyMixin
from app.models.enums import Platform, PlatformAccountStatus


class BrandProfile(UuidPrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, BaseModel):
    __tablename__ = "brand_profile"

    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    language: Mapped[str] = mapped_column(String(32), nullable=False)
    caption_style_defaults: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    overlay_policy: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    music_policy: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    platform_defaults: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class PlatformAccount(UuidPrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, BaseModel):
    __tablename__ = "platform_account"

    brand_profile_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("brand_profile.id"), nullable=False)
    platform: Mapped[Platform] = mapped_column(Enum(Platform, native_enum=False), nullable=False)
    channel_name: Mapped[str] = mapped_column(String(255), nullable=False)
    connection_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    capabilities_jsonb: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[PlatformAccountStatus] = mapped_column(
        Enum(PlatformAccountStatus, native_enum=False),
        nullable=False,
        default=PlatformAccountStatus.active,
    )
