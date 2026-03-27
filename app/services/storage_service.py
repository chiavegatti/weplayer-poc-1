import shutil
from pathlib import Path

import aiofiles
from fastapi import UploadFile

from app.config import settings

ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
ALLOWED_AUDIO_EXTENSIONS = {".mp3", ".aac", ".wav", ".ogg", ".m4a"}
ALLOWED_SUBTITLE_EXTENSIONS = {".srt", ".vtt"}
ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
UPLOAD_CHUNK_SIZE = 64 * 1024 * 1024


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


def get_multipart_dir(upload_id: str) -> Path:
    return settings.storage_dir / "_multipart" / upload_id


def get_multipart_chunk_path(upload_id: str, chunk_index: int) -> Path:
    return get_multipart_dir(upload_id) / f"chunk-{chunk_index:06d}.part"


async def save_upload_chunk(upload_id: str, chunk_index: int, upload: UploadFile) -> Path:
    destination = get_multipart_chunk_path(upload_id, chunk_index)
    destination.parent.mkdir(parents=True, exist_ok=True)
    return await save_upload(upload, destination)


def assemble_upload_chunks(upload_id: str, destination: Path, total_chunks: int) -> Path:
    multipart_dir = get_multipart_dir(upload_id)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as assembled:
        for chunk_index in range(total_chunks):
            chunk_path = get_multipart_chunk_path(upload_id, chunk_index)
            if not chunk_path.exists():
                raise FileNotFoundError(f"Missing upload chunk {chunk_index}")
            with chunk_path.open("rb") as chunk_file:
                shutil.copyfileobj(chunk_file, assembled, length=1024 * 1024)
    shutil.rmtree(multipart_dir, ignore_errors=True)
    return destination


def cleanup_multipart_upload(upload_id: str) -> None:
    shutil.rmtree(get_multipart_dir(upload_id), ignore_errors=True)


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


def resolve_media_path(path_value: str | None) -> Path | None:
    """Resolve absolute or storage-relative media paths to absolute Path."""
    if not path_value:
        return None
    p = Path(path_value)
    if p.is_absolute():
        return p
    return settings.storage_dir / p
