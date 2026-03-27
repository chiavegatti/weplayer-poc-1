import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import UploadFile

from app.services import storage_service as storage
from app.config import settings


def test_validate_extension_video_valid():
    assert storage.validate_extension("video.mp4", storage.ALLOWED_VIDEO_EXTENSIONS) is True
    assert storage.validate_extension("video.MOV", storage.ALLOWED_VIDEO_EXTENSIONS) is True
    assert storage.validate_extension("video.mkv", storage.ALLOWED_VIDEO_EXTENSIONS) is True


def test_validate_extension_video_invalid():
    assert storage.validate_extension("document.pdf", storage.ALLOWED_VIDEO_EXTENSIONS) is False
    assert storage.validate_extension("audio.mp3", storage.ALLOWED_VIDEO_EXTENSIONS) is False


def test_validate_extension_audio():
    assert storage.validate_extension("audio.mp3", storage.ALLOWED_AUDIO_EXTENSIONS) is True
    assert storage.validate_extension("audio.AAC", storage.ALLOWED_AUDIO_EXTENSIONS) is True
    assert storage.validate_extension("video.mp4", storage.ALLOWED_AUDIO_EXTENSIONS) is False


def test_validate_extension_subtitle():
    assert storage.validate_extension("sub.srt", storage.ALLOWED_SUBTITLE_EXTENSIONS) is True
    assert storage.validate_extension("sub.vtt", storage.ALLOWED_SUBTITLE_EXTENSIONS) is True
    assert storage.validate_extension("sub.ass", storage.ALLOWED_SUBTITLE_EXTENSIONS) is False


def test_validate_extension_image():
    assert storage.validate_extension("img.jpg", storage.ALLOWED_IMAGE_EXTENSIONS) is True
    assert storage.validate_extension("img.PNG", storage.ALLOWED_IMAGE_EXTENSIONS) is True
    assert storage.validate_extension("img.gif", storage.ALLOWED_IMAGE_EXTENSIONS) is False


def test_get_input_path_creates_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_dir", tmp_path / "weplayer")
    path = storage.get_input_path("vid-123", "main.mp4")
    assert path.parent.exists()
    assert path.name == "main.mp4"


def test_get_cover_path_creates_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_dir", tmp_path / "weplayer")
    path = storage.get_cover_path("vid-123", "cover.jpg")
    assert path.parent.exists()
    assert path.name == "cover.jpg"


@pytest.mark.asyncio
async def test_save_upload(tmp_path):
    dest = tmp_path / "output.mp4"
    mock_upload = AsyncMock()
    mock_upload.read = AsyncMock(side_effect=[b"chunk1", b"chunk2", b""])

    result = await storage.save_upload(mock_upload, dest)
    assert result == dest
    assert dest.read_bytes() == b"chunk1chunk2"


def test_delete_video_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_dir", tmp_path / "weplayer")
    vid_dir = settings.video_dir("vid-del")
    vid_dir.mkdir(parents=True)
    (vid_dir / "somefile.txt").write_text("data")

    storage.delete_video_storage("vid-del")
    assert not vid_dir.exists()


def test_delete_video_storage_nonexistent(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_dir", tmp_path / "weplayer")
    # Should not raise
    storage.delete_video_storage("nonexistent-id")


def test_get_relative_media_path(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_dir", tmp_path / "weplayer")
    abs_path = tmp_path / "weplayer" / "videos" / "123" / "index.m3u8"
    result = storage.get_relative_media_path(abs_path)
    assert result == "videos/123/index.m3u8"
    assert "\\" not in result


def test_get_relative_media_path_outside_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_dir", tmp_path / "weplayer")
    abs_path = Path("/some/other/path/file.m3u8")
    result = storage.get_relative_media_path(abs_path)
    assert "/" in result


def test_resolve_media_path_relative(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_dir", tmp_path / "weplayer")
    resolved = storage.resolve_media_path("videos/abc/index.m3u8")
    assert resolved == (tmp_path / "weplayer" / "videos" / "abc" / "index.m3u8")


def test_resolve_media_path_absolute(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_dir", tmp_path / "weplayer")
    absolute = tmp_path / "x" / "file.txt"
    resolved = storage.resolve_media_path(str(absolute))
    assert resolved == absolute


def test_resolve_media_path_none(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_dir", tmp_path / "weplayer")
    assert storage.resolve_media_path(None) is None
