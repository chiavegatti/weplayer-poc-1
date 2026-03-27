import uuid
import pytest
from app.models.models import Video, VideoAsset, VideoStatus, AssetType, AssetStatus


def make_video(**kwargs) -> Video:
    defaults = dict(id=str(uuid.uuid4()), title="Test Video", status=VideoStatus.ready)
    defaults.update(kwargs)
    return Video(**defaults)


def make_asset(video_id: str, asset_type: AssetType, **kwargs) -> VideoAsset:
    defaults = dict(id=str(uuid.uuid4()), video_id=video_id, asset_type=asset_type, status=AssetStatus.ready)
    defaults.update(kwargs)
    return VideoAsset(**defaults)


# ── Video model ────────────────────────────────────────────────────────────────

def test_video_repr():
    v = make_video(title="Foo")
    assert "Foo" in repr(v)
    assert "ready" in repr(v)


def test_video_defaults(db_session):
    """SQLAlchemy Column defaults are applied at INSERT time."""
    v = Video(id=str(uuid.uuid4()), title="X")
    db_session.add(v)
    db_session.flush()
    assert v.status == VideoStatus.pending
    assert v.libras_available is False
    assert v.ad_available is False
    assert v.subtitle_available is False


def test_get_hls_manifest_original():
    v = make_video()
    asset = make_asset(v.id, AssetType.hls_original, file_path="videos/1/processed/original/index.m3u8")
    v.assets = [asset]
    assert v.get_hls_manifest("original") == "videos/1/processed/original/index.m3u8"


def test_get_hls_manifest_libras():
    v = make_video()
    asset = make_asset(v.id, AssetType.hls_libras, file_path="videos/1/processed/libras/index.m3u8")
    v.assets = [asset]
    assert v.get_hls_manifest("libras") == "videos/1/processed/libras/index.m3u8"


def test_get_hls_manifest_ad():
    v = make_video()
    asset = make_asset(v.id, AssetType.hls_ad, file_path="videos/1/processed/ad/index.m3u8")
    v.assets = [asset]
    assert v.get_hls_manifest("ad") == "videos/1/processed/ad/index.m3u8"


def test_get_hls_manifest_unknown_variant():
    v = make_video()
    v.assets = []
    assert v.get_hls_manifest("unknown") is None


def test_get_hls_manifest_asset_not_ready():
    v = make_video()
    asset = make_asset(v.id, AssetType.hls_original, status=AssetStatus.error, file_path="x.m3u8")
    v.assets = [asset]
    assert v.get_hls_manifest("original") is None


def test_get_hls_manifest_no_assets():
    v = make_video()
    v.assets = []
    assert v.get_hls_manifest("original") is None


def test_get_subtitle_path():
    v = make_video()
    asset = make_asset(v.id, AssetType.subtitle_vtt, file_path="videos/1/subtitles/subtitle.vtt")
    v.assets = [asset]
    assert v.get_subtitle_path() == "videos/1/subtitles/subtitle.vtt"


def test_get_subtitle_path_no_subtitle():
    v = make_video()
    v.assets = []
    assert v.get_subtitle_path() is None


def test_get_subtitle_path_not_ready():
    v = make_video()
    asset = make_asset(v.id, AssetType.subtitle_vtt, status=AssetStatus.error, file_path="x.vtt")
    v.assets = [asset]
    assert v.get_subtitle_path() is None


# ── VideoAsset model ───────────────────────────────────────────────────────────

def test_asset_repr():
    vid_id = str(uuid.uuid4())
    a = make_asset(vid_id, AssetType.hls_original)
    assert "hls_original" in repr(a)
    assert "ready" in repr(a)


def test_asset_default_status(db_session):
    """SQLAlchemy Column defaults are applied at INSERT time."""
    vid_id = str(uuid.uuid4())
    v = Video(id=vid_id, title="Parent")
    db_session.add(v)
    db_session.flush()
    a = VideoAsset(id=str(uuid.uuid4()), video_id=vid_id, asset_type=AssetType.original_input)
    db_session.add(a)
    db_session.flush()
    assert a.status == AssetStatus.pending


# ── Enum values ────────────────────────────────────────────────────────────────

def test_video_status_values():
    assert VideoStatus.pending == "pending"
    assert VideoStatus.processing == "processing"
    assert VideoStatus.ready == "ready"
    assert VideoStatus.error == "error"


def test_asset_type_values():
    assert AssetType.hls_original == "hls_original"
    assert AssetType.hls_libras == "hls_libras"
    assert AssetType.hls_ad == "hls_ad"
    assert AssetType.subtitle_vtt == "subtitle_vtt"


# ── AdminUser model ────────────────────────────────────────────────────────────

def test_admin_user_repr(db_session):
    from app.models.models import AdminUser
    import uuid
    u = AdminUser(id=str(uuid.uuid4()), email="a@b.com", hashed_password="hash")
    db_session.add(u)
    db_session.flush()
    assert "a@b.com" in repr(u)


def test_admin_user_defaults(db_session):
    from app.models.models import AdminUser
    import uuid
    u = AdminUser(id=str(uuid.uuid4()), email="x@y.com", hashed_password="hash")
    db_session.add(u)
    db_session.flush()
    assert u.created_at is not None


def test_admin_user_unique_email(db_session):
    from app.models.models import AdminUser
    import uuid
    from sqlalchemy.exc import IntegrityError
    u1 = AdminUser(id=str(uuid.uuid4()), email="dup@test.com", hashed_password="h1")
    u2 = AdminUser(id=str(uuid.uuid4()), email="dup@test.com", hashed_password="h2")
    db_session.add(u1)
    db_session.flush()
    db_session.add(u2)
    with pytest.raises(IntegrityError):
        db_session.flush()
