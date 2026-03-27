import io
import uuid
import pytest
from unittest.mock import patch, MagicMock
from app.models.models import Video, VideoStatus, AssetType, AssetStatus, VideoAsset
from tests.conftest import TestingSessionLocal


def make_video(db, status=VideoStatus.ready, **kwargs) -> Video:
    v = Video(
        id=str(uuid.uuid4()),
        title=kwargs.get("title", "Test Video"),
        description=kwargs.get("description", None),
        status=status,
        libras_available=kwargs.get("libras_available", False),
        ad_available=kwargs.get("ad_available", False),
        subtitle_available=kwargs.get("subtitle_available", False),
    )
    db.add(v)
    db.commit()
    db.refresh(v)
    return v


# ── Auth ──────────────────────────────────────────────────────────────────────

def test_login_page(client):
    r = client.get("/admin/login")
    assert r.status_code == 200
    assert "Painel Administrativo" in r.text


def test_login_success(client):
    r = client.post("/admin/login", data={"username": "admin", "password": "admin123"})
    assert r.status_code == 200  # follows redirect
    assert "weplayer_session" in client.cookies


def test_login_invalid_credentials(client):
    r = client.post("/admin/login", data={"username": "admin", "password": "wrong"})
    assert r.status_code == 401
    assert "inválidos" in r.text


def test_logout(auth_client):
    r = auth_client.get("/admin/logout")
    assert r.status_code == 200
    assert "weplayer_session" not in auth_client.cookies


def test_dashboard_requires_auth(client):
    r = client.get("/admin/dashboard", follow_redirects=False)
    assert r.status_code == 401


# ── Dashboard ─────────────────────────────────────────────────────────────────

def test_dashboard_empty(auth_client):
    r = auth_client.get("/admin/dashboard")
    assert r.status_code == 200
    assert "Nenhum vídeo" in r.text


def test_dashboard_with_videos(auth_client):
    db = TestingSessionLocal()
    make_video(db, title="Meu Vídeo", libras_available=True)
    db.close()

    r = auth_client.get("/admin/dashboard")
    assert r.status_code == 200
    assert "Meu Vídeo" in r.text
    assert "Libras" in r.text


# ── New Video Form ─────────────────────────────────────────────────────────────

def test_new_video_form(auth_client):
    r = auth_client.get("/admin/videos/new")
    assert r.status_code == 200
    assert "Novo Vídeo" in r.text


def test_new_video_form_requires_auth(client):
    r = client.get("/admin/videos/new", follow_redirects=False)
    assert r.status_code == 401


def _fake_video_file(filename="video.mp4", content=b"fake-video-data"):
    return ("video_file", (filename, io.BytesIO(content), "video/mp4"))


def _fake_file(field, filename, content=b"data", mime="application/octet-stream"):
    return (field, (filename, io.BytesIO(content), mime))


def test_create_video_minimal(auth_client, tmp_path, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "storage_dir", tmp_path / "weplayer")
    (tmp_path / "weplayer" / "videos").mkdir(parents=True, exist_ok=True)

    with patch("app.routes.admin._process_video"):
        r = auth_client.post(
            "/admin/videos/new",
            files=[_fake_video_file()],
            data={"title": "My Video", "description": ""},
        )
    assert r.status_code == 200
    assert "My Video" in r.text or r.url.path.startswith("/admin/videos/")


def test_create_video_invalid_extension(auth_client):
    r = auth_client.post(
        "/admin/videos/new",
        files=[_fake_file("video_file", "document.pdf")],
        data={"title": "Bad Video"},
    )
    assert r.status_code == 422
    assert "inválido" in r.text


def test_create_video_with_all_assets(auth_client, tmp_path, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "storage_dir", tmp_path / "weplayer")
    (tmp_path / "weplayer" / "videos").mkdir(parents=True, exist_ok=True)

    with patch("app.routes.admin._process_video"):
        r = auth_client.post(
            "/admin/videos/new",
            files=[
                _fake_video_file(),
                _fake_file("libras_file", "libras.mp4"),
                _fake_file("ad_file", "ad.mp3", mime="audio/mpeg"),
                _fake_file("subtitle_file", "sub.srt", mime="text/plain"),
                _fake_file("cover_file", "cover.jpg", mime="image/jpeg"),
            ],
            data={"title": "Full Video", "description": "All assets"},
        )
    assert r.status_code == 200


# ── Video Detail ──────────────────────────────────────────────────────────────

def test_video_detail(auth_client):
    db = TestingSessionLocal()
    v = make_video(db, status=VideoStatus.ready)
    vid_id = v.id
    db.close()

    r = auth_client.get(f"/admin/videos/{vid_id}")
    assert r.status_code == 200
    assert "Test Video" in r.text


def test_video_detail_not_found(auth_client):
    r = auth_client.get("/admin/videos/nonexistent-id")
    assert r.status_code == 404


def test_video_detail_requires_auth(client):
    r = client.get("/admin/videos/some-id", follow_redirects=False)
    assert r.status_code == 401


def test_video_detail_with_assets(auth_client):
    db = TestingSessionLocal()
    v = make_video(db, status=VideoStatus.ready)
    asset = VideoAsset(
        id=str(uuid.uuid4()),
        video_id=v.id,
        asset_type=AssetType.hls_original,
        file_path="videos/x/processed/original/index.m3u8",
        status=AssetStatus.ready,
    )
    db.add(asset)
    db.commit()
    vid_id = v.id
    db.close()

    r = auth_client.get(f"/admin/videos/{vid_id}")
    assert r.status_code == 200
    assert "hls_original" in r.text


def test_video_detail_with_error_status(auth_client):
    db = TestingSessionLocal()
    v = Video(
        id=str(uuid.uuid4()),
        title="Broken",
        status=VideoStatus.error,
        error_message="FFmpeg crashed",
    )
    db.add(v)
    db.commit()
    vid_id = v.id
    db.close()

    r = auth_client.get(f"/admin/videos/{vid_id}")
    assert r.status_code == 200
    assert "FFmpeg crashed" in r.text


# ── Reprocess ─────────────────────────────────────────────────────────────────

def test_reprocess_no_input_file(auth_client):
    db = TestingSessionLocal()
    v = make_video(db, status=VideoStatus.error)
    vid_id = v.id
    db.close()

    r = auth_client.post(f"/admin/videos/{vid_id}/reprocess")
    assert r.status_code == 400


def test_reprocess_with_input_file(auth_client, tmp_path, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "storage_dir", tmp_path / "weplayer")

    fake_input = tmp_path / "weplayer" / "videos" / "vid-rp" / "input" / "main.mp4"
    fake_input.parent.mkdir(parents=True)
    fake_input.write_bytes(b"fake")

    db = TestingSessionLocal()
    v = Video(id="vid-rp", title="Reprocess Me", status=VideoStatus.error)
    asset = VideoAsset(
        id=str(uuid.uuid4()),
        video_id="vid-rp",
        asset_type=AssetType.original_input,
        file_path=str(fake_input),
        status=AssetStatus.ready,
    )
    db.add(v)
    db.add(asset)
    db.commit()
    db.close()

    with patch("app.routes.admin._process_video"):
        r = auth_client.post("/admin/videos/vid-rp/reprocess")
    assert r.status_code == 200


def test_reprocess_not_found(auth_client):
    r = auth_client.post("/admin/videos/nonexistent/reprocess")
    assert r.status_code == 404


# ── Delete ────────────────────────────────────────────────────────────────────

def test_delete_video(auth_client):
    db = TestingSessionLocal()
    v = make_video(db)
    vid_id = v.id
    db.close()

    r = auth_client.post(f"/admin/videos/{vid_id}/delete")
    assert r.status_code == 200

    db = TestingSessionLocal()
    assert db.query(Video).get(vid_id) is None
    db.close()


def test_delete_video_not_found(auth_client):
    r = auth_client.post("/admin/videos/nonexistent/delete")
    assert r.status_code == 404


# ── Docs ──────────────────────────────────────────────────────────────────────

def test_docs_page(auth_client):
    r = auth_client.get("/admin/docs")
    assert r.status_code == 200
    assert "Documentação" in r.text
    assert "Tutorial" in r.text


def test_docs_requires_auth(client):
    r = client.get("/admin/docs", follow_redirects=False)
    assert r.status_code == 401


# ── DB-based login ─────────────────────────────────────────────────────────────

def test_login_with_db_admin_user(client):
    from app.auth import hash_password
    from app.models.models import AdminUser
    db = TestingSessionLocal()
    user = AdminUser(email="iguale@iguale.com.br", hashed_password=hash_password("acesso10@123"))
    db.add(user)
    db.commit()
    db.close()

    r = client.post(
        "/admin/login",
        data={"username": "iguale@iguale.com.br", "password": "acesso10@123"},
        follow_redirects=False,
    )
    assert r.status_code == 302
    assert "weplayer_session" in client.cookies


# ── Video Status API ──────────────────────────────────────────────────────────

def test_video_status_api(auth_client):
    db = TestingSessionLocal()
    v = make_video(db, status=VideoStatus.processing)
    vid_id = v.id
    db.close()

    r = auth_client.get(f"/admin/videos/{vid_id}/status")
    assert r.status_code == 200
    data = r.json()
    assert data["id"] == vid_id
    assert data["status"] == "processing"
    assert data["title"] == "Test Video"


def test_video_status_api_ready(auth_client):
    db = TestingSessionLocal()
    v = make_video(db, status=VideoStatus.ready, title="Ready Vid")
    vid_id = v.id
    db.close()

    r = auth_client.get(f"/admin/videos/{vid_id}/status")
    assert r.status_code == 200
    assert r.json()["status"] == "ready"


def test_video_status_api_not_found(auth_client):
    r = auth_client.get("/admin/videos/nonexistent-id/status")
    assert r.status_code == 404


def test_video_status_api_requires_auth(client):
    r = client.get("/admin/videos/some-id/status", follow_redirects=False)
    assert r.status_code == 401
