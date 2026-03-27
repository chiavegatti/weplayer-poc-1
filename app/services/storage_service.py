import shutil
from pathlib import Path

import aiofiles
from fastapi import UploadFile

from app.config import settings

ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
ALLOWED_AUDIO_EXTENSIONS = {".mp3", ".aac", ".wav", ".ogg", ".m4a"}
ALLOWED_SUBTITLE_EXTENSIONS = {".srt", ".vtt"}
ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


def validate_extension(filename: str, allowed: set[str]) -> bool:
    return Path(filename).suffix.lower() in allowed


def get_input_path(video_id: str, filename: str) -> Path:
    directory = settings.video_input_dir(video_id)
    directory.mkdir(parents=True, exist_ok=True)
    return directory / filename


def get_cover_path(video_id: str, filename: str) -> Path:
    directory = settings.video_covers_dir(video_id)
    directory.mkdir(parents=True, exist_ok=True)
    return directory / filename


async def save_upload(upload: UploadFile, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    async with aiofiles.open(destination, "wb") as f:
        while chunk := await upload.read(1024 * 1024):  # 1MB chunks
            await f.write(chunk)
    return destination


def delete_video_storage(video_id: str) -> None:
    video_dir = settings.video_dir(video_id)
    if video_dir.exists():
        shutil.rmtree(video_dir)


def get_relative_media_path(absolute_path: Path) -> str:
    """Return URL-friendly path relative to storage_dir for use with /media/ route."""
    try:
        rel = absolute_path.relative_to(settings.storage_dir)
        return str(rel).replace("\\", "/")
    except ValueError:
        return str(absolute_path).replace("\\", "/")
