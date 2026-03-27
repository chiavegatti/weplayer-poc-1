from pathlib import Path
from app.config import Settings, settings


def test_settings_defaults():
    s = Settings()
    assert s.app_name == "WePlayer"
    assert s.app_version == "0.1.0"
    assert s.session_cookie_name == "weplayer_session"
    assert s.session_max_age == 60 * 60 * 8


def test_settings_videos_dir():
    assert settings.videos_dir == settings.storage_dir / "videos"


def test_settings_video_dir():
    d = settings.video_dir("abc123")
    assert d == settings.storage_dir / "videos" / "abc123"


def test_settings_video_input_dir():
    d = settings.video_input_dir("abc123")
    assert "input" in str(d)


def test_settings_video_processed_dir():
    d = settings.video_processed_dir("abc123", "original")
    assert "original" in str(d)
    assert "processed" in str(d)


def test_settings_video_subtitles_dir():
    d = settings.video_subtitles_dir("abc123")
    assert "subtitles" in str(d)


def test_settings_video_covers_dir():
    d = settings.video_covers_dir("abc123")
    assert "covers" in str(d)


def test_settings_video_logs_dir():
    d = settings.video_logs_dir("abc123")
    assert "logs" in str(d)
