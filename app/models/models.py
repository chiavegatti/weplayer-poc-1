import uuid
from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Text, Enum
from sqlalchemy.orm import relationship, DeclarativeBase


class Base(DeclarativeBase):
    pass


class VideoStatus(str, PyEnum):
    pending = "pending"
    processing = "processing"
    ready = "ready"
    error = "error"


class AssetType(str, PyEnum):
    original_input = "original_input"
    libras_input = "libras_input"
    ad_input = "ad_input"
    subtitle_input = "subtitle_input"
    hls_original = "hls_original"
    hls_libras = "hls_libras"
    hls_ad = "hls_ad"
    subtitle_vtt = "subtitle_vtt"


class AssetStatus(str, PyEnum):
    pending = "pending"
    processing = "processing"
    ready = "ready"
    error = "error"


class Video(Base):
    __tablename__ = "videos"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    cover_path = Column(String(512), nullable=True)
    status = Column(Enum(VideoStatus), nullable=False, default=VideoStatus.pending)
    libras_available = Column(Boolean, nullable=False, default=False)
    libras_scale = Column(String(10), nullable=False, default="25")
    ad_available = Column(Boolean, nullable=False, default=False)
    subtitle_available = Column(Boolean, nullable=False, default=False)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    assets = relationship("VideoAsset", back_populates="video", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Video id={self.id!r} title={self.title!r} status={self.status}>"

    def get_hls_manifest(self, variant: str) -> str | None:
        """Return the HLS manifest path for the given variant."""
        type_map = {
            "original": AssetType.hls_original,
            "libras": AssetType.hls_libras,
            "ad": AssetType.hls_ad,
        }
        asset_type = type_map.get(variant)
        if not asset_type:
            return None
        for asset in self.assets:
            if asset.asset_type == asset_type and asset.status == AssetStatus.ready:
                return asset.file_path
        return None

    def get_subtitle_path(self) -> str | None:
        for asset in self.assets:
            if asset.asset_type == AssetType.subtitle_vtt and asset.status == AssetStatus.ready:
                return asset.file_path
        return None


class VideoAsset(Base):
    __tablename__ = "video_assets"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    video_id = Column(String(36), ForeignKey("videos.id"), nullable=False)
    asset_type = Column(Enum(AssetType), nullable=False)
    file_path = Column(String(512), nullable=True)
    status = Column(Enum(AssetStatus), nullable=False, default=AssetStatus.pending)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    video = relationship("Video", back_populates="assets")

    def __repr__(self) -> str:
        return f"<VideoAsset id={self.id!r} type={self.asset_type} status={self.status}>"


class AdminUser(Base):
    __tablename__ = "admin_users"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email = Column(String(255), nullable=False, unique=True, index=True)
    hashed_password = Column(String(255), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<AdminUser id={self.id!r} email={self.email!r}>"
