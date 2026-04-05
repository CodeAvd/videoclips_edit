from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict

ItemT = TypeVar("ItemT")


class AppSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class TimestampedOut(AppSchema):
    created_at: datetime


class ListResponse(AppSchema, Generic[ItemT]):
    items: list[ItemT]
    next_cursor: str | None = None
