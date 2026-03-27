"""Tests for the background processing job in admin routes."""
import uuid
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from app.models.models import Video, VideoAsset, VideoStatus, AssetType, AssetStatus
from app.routes.admin import _process_video, _upsert_asset, _fail_video, _read_logs
from app.config import settings
from tests.conftest import TestingSessionLocal


def make_video_in_db(db, video_id: str, status=VideoStatus.pending) -> Video:
    v = Video(id=video_id, title="Job Test", status=status)
    db.add(v)
    db.commit()
    return v


# ── _upsert_asset ─────────────────────────────────────────────────────────────

def test_upsert_asset_creates_new(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_dir", tmp_path / "weplayer")
    db = TestingSessionLocal()
    vid_id = str(uuid.uuid4())
    make_video_in_db(db, vid_id)

    manifest = tmp_path / "weplayer" / "videos" / vid_id / "processed" / "original" / "index.m3u8"
    manifest.parent.mkdir(parents=True)
    manifest.touch()

    _upsert_asset(db, vid_id, AssetType.hls_original, manifest)
    asset = db.query(VideoAsset).filter_by(video_id=vid_id, asset_type=AssetType.hls_original).first()
    assert asset is not None
    assert asset.status == AssetStatus.ready
    db.close()


def test_upsert_asset_updates_existing(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_dir", tmp_path / "weplayer")
    db = TestingSessionLocal()
    vid_id = str(uuid.uuid4())
    make_video_in_db(db, vid_id)

    existing = VideoAsset(
        id=str(uuid.uuid4()),
        video_id=vid_id,
        asset_type=AssetType.hls_original,
        status=AssetStatus.error,
    )
    db.add(existing)
    db.commit()

    manifest = tmp_path / "weplayer" / "videos" / vid_id / "processed" / "original" / "index.m3u8"
    manifest.parent.mkdir(parents=True)
    manifest.touch()

    _upsert_asset(db, vid_id, AssetType.hls_original, manifest)
    asset = db.query(VideoAsset).filter_by(video_id=vid_id, asset_type=AssetType.hls_original).first()
    assert asset.status == AssetStatus.ready
    db.close()


def test_upsert_asset_error(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_dir", tmp_path / "weplayer")
    db = TestingSessionLocal()
    vid_id = str(uuid.uuid4())
    make_video_in_db(db, vid_id)

    _upsert_asset(db, vid_id, AssetType.hls_libras, None, error="FFmpeg failed")
    asset = db.query(VideoAsset).filter_by(video_id=vid_id, asset_type=AssetType.hls_libras).first()
    assert asset.status == AssetStatus.error
    assert "FFmpeg failed" in asset.error_message
    db.close()


# ── _fail_video ───────────────────────────────────────────────────────────────

def test_fail_video(tmp_path, monkeypatch):
    db = TestingSessionLocal()
    vid_id = str(uuid.uuid4())
    make_video_in_db(db, vid_id)
    db.close()

    db2 = TestingSessionLocal()
    _fail_video(db2, vid_id, "Something went wrong")
    v = db2.query(Video).get(vid_id)
    assert v.status == VideoStatus.error
    assert "Something went wrong" in v.error_message
    db2.close()


def test_fail_video_nonexistent():
    db = TestingSessionLocal()
    # Should not raise
    _fail_video(db, "nonexistent-id", "error")
    db.close()


# ── _process_video ────────────────────────────────────────────────────────────

def test_process_video_success(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_dir", tmp_path / "weplayer")

    db = TestingSessionLocal()
    vid_id = str(uuid.uuid4())
    make_video_in_db(db, vid_id)
    db.close()

    fake_manifest = tmp_path / "index.m3u8"
    fake_manifest.touch()

    with patch("app.services.ffmpeg_service.process_original_hls", return_value=fake_manifest), \
         patch("app.routes.admin._upsert_asset"):
        _process_video(
            video_id=vid_id,
            main_input=tmp_path / "main.mp4",
            libras_input=None,
            ad_input=None,
            subtitle_input=None,
            _session_factory=TestingSessionLocal,
        )

    db = TestingSessionLocal()
    v = db.query(Video).get(vid_id)
    assert v.status == VideoStatus.ready
    db.close()


def test_process_video_ffmpeg_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_dir", tmp_path / "weplayer")

    db = TestingSessionLocal()
    vid_id = str(uuid.uuid4())
    make_video_in_db(db, vid_id)
    db.close()

    with patch("app.services.ffmpeg_service.process_original_hls", side_effect=RuntimeError("boom")):
        _process_video(
            video_id=vid_id,
            main_input=tmp_path / "main.mp4",
            libras_input=None,
            ad_input=None,
            subtitle_input=None,
            _session_factory=TestingSessionLocal,
        )

    db = TestingSessionLocal()
    v = db.query(Video).get(vid_id)
    assert v.status == VideoStatus.error
    assert "boom" in v.error_message
    db.close()


def test_process_video_libras_failure_does_not_stop_pipeline(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_dir", tmp_path / "weplayer")

    db = TestingSessionLocal()
    vid_id = str(uuid.uuid4())
    make_video_in_db(db, vid_id)
    db.close()

    fake_manifest = tmp_path / "index.m3u8"
    fake_manifest.touch()

    with patch("app.services.ffmpeg_service.process_original_hls", return_value=fake_manifest), \
         patch("app.services.ffmpeg_service.process_libras_hls", side_effect=RuntimeError("libras fail")), \
         patch("app.routes.admin._upsert_asset"):
        _process_video(
            video_id=vid_id,
            main_input=tmp_path / "main.mp4",
            libras_input=tmp_path / "libras.mp4",
            ad_input=None,
            subtitle_input=None,
            _session_factory=TestingSessionLocal,
        )

    db = TestingSessionLocal()
    v = db.query(Video).get(vid_id)
    # Original succeeded, so overall status is ready
    assert v.status == VideoStatus.ready
    assert v.libras_available is False
    db.close()


def test_process_video_nonexistent_id(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_dir", tmp_path / "weplayer")
    # Should not raise
    _process_video(
        video_id="nonexistent",
        main_input=tmp_path / "main.mp4",
        libras_input=None,
        ad_input=None,
        subtitle_input=None,
        _session_factory=TestingSessionLocal,
    )


def test_process_video_ad_failure_continues(tmp_path, monkeypatch):
    """AD failure should not stop pipeline — video ends as ready with ad_available=False."""
    monkeypatch.setattr(settings, "storage_dir", tmp_path / "weplayer")

    db = TestingSessionLocal()
    vid_id = str(uuid.uuid4())
    make_video_in_db(db, vid_id)
    db.close()

    fake_manifest = tmp_path / "index.m3u8"
    fake_manifest.touch()

    with patch("app.services.ffmpeg_service.process_original_hls", return_value=fake_manifest), \
         patch("app.services.ffmpeg_service.process_ad_hls", side_effect=RuntimeError("ad fail")), \
         patch("app.routes.admin._upsert_asset"):
        _process_video(
            video_id=vid_id,
            main_input=tmp_path / "main.mp4",
            libras_input=None,
            ad_input=tmp_path / "ad.mp3",
            subtitle_input=None,
            _session_factory=TestingSessionLocal,
        )

    db = TestingSessionLocal()
    v = db.query(Video).get(vid_id)
    assert v.status == VideoStatus.ready
    assert v.ad_available is False
    db.close()


def test_process_video_subtitle_failure_continues(tmp_path, monkeypatch):
    """Subtitle failure should not stop pipeline."""
    monkeypatch.setattr(settings, "storage_dir", tmp_path / "weplayer")

    db = TestingSessionLocal()
    vid_id = str(uuid.uuid4())
    make_video_in_db(db, vid_id)
    db.close()

    fake_manifest = tmp_path / "index.m3u8"
    fake_manifest.touch()

    with patch("app.services.ffmpeg_service.process_original_hls", return_value=fake_manifest), \
         patch("app.services.ffmpeg_service.process_subtitle_vtt", side_effect=RuntimeError("sub fail")), \
         patch("app.routes.admin._upsert_asset"):
        _process_video(
            video_id=vid_id,
            main_input=tmp_path / "main.mp4",
            libras_input=None,
            ad_input=None,
            subtitle_input=tmp_path / "sub.srt",
            _session_factory=TestingSessionLocal,
        )

    db = TestingSessionLocal()
    v = db.query(Video).get(vid_id)
    assert v.status == VideoStatus.ready
    assert v.subtitle_available is False
    db.close()


def test_process_video_with_all_assets_success(tmp_path, monkeypatch):
    """Full pipeline with all assets succeeds."""
    monkeypatch.setattr(settings, "storage_dir", tmp_path / "weplayer")

    db = TestingSessionLocal()
    vid_id = str(uuid.uuid4())
    make_video_in_db(db, vid_id)
    db.close()

    fake_manifest = tmp_path / "index.m3u8"
    fake_vtt = tmp_path / "sub.vtt"
    fake_manifest.touch()
    fake_vtt.touch()

    with patch("app.services.ffmpeg_service.process_original_hls", return_value=fake_manifest), \
         patch("app.services.ffmpeg_service.process_libras_hls", return_value=fake_manifest), \
         patch("app.services.ffmpeg_service.process_ad_hls", return_value=fake_manifest), \
         patch("app.services.ffmpeg_service.process_subtitle_vtt", return_value=fake_vtt), \
         patch("app.routes.admin._upsert_asset"):
        _process_video(
            video_id=vid_id,
            main_input=tmp_path / "main.mp4",
            libras_input=tmp_path / "libras.mp4",
            ad_input=tmp_path / "ad.mp3",
            subtitle_input=tmp_path / "sub.srt",
            _session_factory=TestingSessionLocal,
        )

    db = TestingSessionLocal()
    v = db.query(Video).get(vid_id)
    assert v.status == VideoStatus.ready
    assert v.libras_available is True
    assert v.ad_available is True
    assert v.subtitle_available is True
    db.close()


# ── _read_logs ────────────────────────────────────────────────────────────────

def test_read_logs(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_dir", tmp_path / "weplayer")
    log_dir = settings.video_logs_dir("vid-log")
    log_dir.mkdir(parents=True)
    (log_dir / "original.log").write_text("log content here")

    logs = _read_logs("vid-log")
    assert "original" in logs
    assert "log content here" in logs["original"]


def test_read_logs_no_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_dir", tmp_path / "weplayer")
    logs = _read_logs("nonexistent-vid")
    assert logs == {}
