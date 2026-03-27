import uuid
import pytest
from app.models.models import Video, VideoStatus
from tests.conftest import TestingSessionLocal


def make_video(db, **kwargs) -> Video:
    v = Video(
        id=str(uuid.uuid4()),
        title=kwargs.get("title", "API Video"),
        status=kwargs.get("status", VideoStatus.ready),
    )
    db.add(v)
    db.commit()
    db.refresh(v)
    return v


# ── Authenticated API ──────────────────────────────────────────────────────────

def test_api_list_videos_requires_auth(client):
    r = client.get("/api/videos", follow_redirects=False)
    assert r.status_code == 401


def test_api_list_videos_empty(auth_client):
    r = auth_client.get("/api/videos")
    assert r.status_code == 200
    assert r.json() == []


def test_api_list_videos(auth_client):
    db = TestingSessionLocal()
    make_video(db, title="API Test")
    db.close()

    r = auth_client.get("/api/videos")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]["title"] == "API Test"


def test_api_get_video(auth_client):
    db = TestingSessionLocal()
    v = make_video(db, title="Single Video")
    vid_id = v.id
    db.close()

    r = auth_client.get(f"/api/videos/{vid_id}")
    assert r.status_code == 200
    assert r.json()["title"] == "Single Video"


def test_api_get_video_not_found(auth_client):
    r = auth_client.get("/api/videos/nonexistent")
    assert r.status_code == 404


# ── Public API ────────────────────────────────────────────────────────────────

def test_api_public_videos_empty(client):
    r = client.get("/api/public/videos")
    assert r.status_code == 200
    assert r.json() == []


def test_api_public_videos_only_ready(client):
    db = TestingSessionLocal()
    make_video(db, title="Ready One", status=VideoStatus.ready)
    make_video(db, title="Pending One", status=VideoStatus.pending)
    make_video(db, title="Error One", status=VideoStatus.error)
    db.close()

    r = client.get("/api/public/videos")
    assert r.status_code == 200
    data = r.json()
    titles = [v["title"] for v in data]
    assert "Ready One" in titles
    assert "Pending One" not in titles
    assert "Error One" not in titles


def test_api_video_schema_fields(auth_client):
    db = TestingSessionLocal()
    make_video(db, title="Schema Check")
    db.close()

    r = auth_client.get("/api/videos")
    data = r.json()[0]
    for field in ["id", "title", "status", "libras_available", "ad_available",
                  "subtitle_available", "created_at", "updated_at", "assets"]:
        assert field in data
