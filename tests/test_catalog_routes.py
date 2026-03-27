import uuid
import pytest
from app.models.models import Video, VideoAsset, VideoStatus, AssetType, AssetStatus
from tests.conftest import TestingSessionLocal


def make_ready_video(db, **kwargs) -> Video:
    vid_id = str(uuid.uuid4())
    v = Video(
        id=vid_id,
        title=kwargs.get("title", "Ready Video"),
        description=kwargs.get("description", "A description"),
        status=VideoStatus.ready,
        libras_available=kwargs.get("libras_available", False),
        ad_available=kwargs.get("ad_available", False),
        subtitle_available=kwargs.get("subtitle_available", False),
    )
    db.add(v)

    # Add HLS original asset
    asset = VideoAsset(
        id=str(uuid.uuid4()),
        video_id=vid_id,
        asset_type=AssetType.hls_original,
        file_path=f"videos/{vid_id}/processed/original/index.m3u8",
        status=AssetStatus.ready,
    )
    db.add(asset)
    db.commit()
    db.refresh(v)
    return v


# â”€â”€ Index â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def test_index(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "WePlayer" in r.text


def test_index_has_catalog_link(client):
    r = client.get("/")
    assert "/catalog" in r.text


# â”€â”€ Catalog â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def test_catalog_empty(client):
    r = client.get("/catalog")
    assert r.status_code == 200
    assert "Nenhum vÃ­deo" in r.text


def test_catalog_shows_ready_videos(client):
    db = TestingSessionLocal()
    make_ready_video(db, title="Accessible Film", libras_available=True, ad_available=True)
    db.close()

    r = client.get("/catalog")
    assert r.status_code == 200
    assert "Accessible Film" in r.text
    assert "Libras" in r.text
    assert "AD" in r.text


def test_catalog_hides_pending_videos(client):
    db = TestingSessionLocal()
    v = Video(id=str(uuid.uuid4()), title="Pending Video", status=VideoStatus.pending)
    db.add(v)
    db.commit()
    db.close()

    r = client.get("/catalog")
    assert "Pending Video" not in r.text


def test_catalog_hides_error_videos(client):
    db = TestingSessionLocal()
    v = Video(id=str(uuid.uuid4()), title="Error Video", status=VideoStatus.error)
    db.add(v)
    db.commit()
    db.close()

    r = client.get("/catalog")
    assert "Error Video" not in r.text


def test_catalog_multiple_videos(client):
    db = TestingSessionLocal()
    make_ready_video(db, title="Video Alpha")
    make_ready_video(db, title="Video Beta")
    db.close()

    r = client.get("/catalog")
    assert "Video Alpha" in r.text
    assert "Video Beta" in r.text


# â”€â”€ Player â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def test_watch_ready_video(client):
    db = TestingSessionLocal()
    v = make_ready_video(db, title="Watch Me")
    vid_id = v.id
    db.close()

    r = client.get(f"/watch/{vid_id}")
    assert r.status_code == 200
    assert "Watch Me" in r.text
    assert "shaka" in r.text.lower()


def test_watch_video_not_found(client):
    r = client.get("/watch/nonexistent-id")
    assert r.status_code == 404


def test_watch_pending_video_returns_404(client):
    db = TestingSessionLocal()
    v = Video(id=str(uuid.uuid4()), title="Not Yet", status=VideoStatus.pending)
    db.add(v)
    db.commit()
    vid_id = v.id
    db.close()

    r = client.get(f"/watch/{vid_id}")
    assert r.status_code == 404


def test_watch_video_with_all_features(client):
    db = TestingSessionLocal()
    vid_id = str(uuid.uuid4())
    v = Video(
        id=vid_id,
        title="Full Featured",
        status=VideoStatus.ready,
        libras_available=True,
        ad_available=True,
        subtitle_available=True,
    )
    db.add(v)

    for asset_type, path_suffix in [
        (AssetType.hls_original, "original/index.m3u8"),
        (AssetType.hls_libras, "libras/index.m3u8"),
        (AssetType.hls_ad, "ad/index.m3u8"),
        (AssetType.subtitle_vtt, "subtitles/subtitle.vtt"),
    ]:
        db.add(VideoAsset(
            id=str(uuid.uuid4()),
            video_id=vid_id,
            asset_type=asset_type,
            file_path=f"videos/{vid_id}/processed/{path_suffix}",
            status=AssetStatus.ready,
        ))
    db.commit()
    db.close()

    r = client.get(f"/watch/{vid_id}")
    assert r.status_code == 200
    assert "Libras" in r.text
    assert "AD" in r.text
