from datetime import datetime
from pydantic import BaseModel, Field
from app.models.models import VideoStatus, AssetType, AssetStatus


class VideoAssetOut(BaseModel):
    id: str
    asset_type: AssetType
    file_path: str | None
    status: AssetStatus
    created_at: datetime

    model_config = {"from_attributes": True}


class VideoOut(BaseModel):
    id: str
    title: str
    description: str | None
    cover_path: str | None
    status: VideoStatus
    libras_available: bool
    ad_available: bool
    subtitle_available: bool
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    assets: list[VideoAssetOut] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class VideoCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
