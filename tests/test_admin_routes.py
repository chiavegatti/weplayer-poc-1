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


# â”€â”€ Auth â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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
    assert "invÃ¡lidos" in r.text


def test_logout(auth_client):
    r = auth_client.get("/admin/logout")
    assert r.status_code == 200
    assert "weplayer_session" not in auth_client.cookies


def test_dashboard_requires_auth(client):
    r = client.get("/admin/dashboard", follow_redirects=False)
    assert r.status_code == 401


# â”€â”€ Dashboard â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def test_dashboard_empty(auth_client):
    r = auth_client.get("/admin/dashboard")
    assert r.status_code == 200
    assert "Nenhum vídeo" in r.text


def test_dashboard_with_videos(auth_client):
    db = TestingSessionLocal()
    make_video(db, title="Meu VÃ­deo", libras_available=True)
    db.close()

    r = auth_client.get("/admin/dashboard")
    assert r.status_code == 200
    assert "Meu VÃ­deo" in r.text
    assert "Libras" in r.text


# â”€â”€ New Video Form â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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
    assert "invÃ¡lido" in r.text


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

def test_initiate_chunk_upload(auth_client):
    r = auth_client.post(
        "/admin/uploads/initiate",
        data={"field_name": "video_file", "filename": "video.mp4"},
    )
    assert r.status_code == 200
    payload = r.json()
    assert "upload_id" in payload
    assert payload["chunk_size"] == 64 * 1024 * 1024


def test_create_video_from_chunk_upload(auth_client, tmp_path, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "storage_dir", tmp_path / "weplayer")
    (tmp_path / "weplayer" / "videos").mkdir(parents=True, exist_ok=True)

    def push_chunked_upload(field_name, filename, chunks):
        init = auth_client.post(
            "/admin/uploads/initiate",
            data={"field_name": field_name, "filename": filename},
        )
        upload_id = init.json()["upload_id"]
        for index, chunk in enumerate(chunks):
            auth_client.post(
                f"/admin/uploads/{upload_id}/chunk",
                data={"chunk_index": str(index)},
                files={"chunk": (f"{filename}.part", io.BytesIO(chunk), "application/octet-stream")},
            )
        return upload_id, len(chunks), filename

    video_upload_id, video_chunk_total, video_filename = push_chunked_upload(
        "video_file",
        "video.mp4",
        [b"chunk-a", b"chunk-b"],
    )
    libras_upload_id, libras_chunk_total, libras_filename = push_chunked_upload(
        "libras_file",
        "libras.mp4",
        [b"libras-a", b"libras-b"],
    )
    ad_upload_id, ad_chunk_total, ad_filename = push_chunked_upload(
        "ad_file",
        "ad.mp3",
        [b"ad-a", b"ad-b"],
    )

    with patch("app.routes.admin._process_video"):
        r = auth_client.post(
            "/admin/videos/new",
            data={
                "title": "Chunked Video",
                "description": "big upload",
                "video_chunk_upload_id": video_upload_id,
                "video_chunk_total": str(video_chunk_total),
                "video_chunk_filename": video_filename,
                "libras_chunk_upload_id": libras_upload_id,
                "libras_chunk_total": str(libras_chunk_total),
                "libras_chunk_filename": libras_filename,
                "ad_chunk_upload_id": ad_upload_id,
                "ad_chunk_total": str(ad_chunk_total),
                "ad_chunk_filename": ad_filename,
            },
        )

    assert r.status_code == 200
    saved_main = list((tmp_path / "weplayer" / "videos").glob("*/input/main.mp4"))
    saved_libras = list((tmp_path / "weplayer" / "videos").glob("*/input/libras.mp4"))
    saved_ad = list((tmp_path / "weplayer" / "videos").glob("*/input/ad.mp3"))
    assert len(saved_main) == 1
    assert len(saved_libras) == 1
    assert len(saved_ad) == 1
    assert saved_main[0].read_bytes() == b"chunk-achunk-b"
    assert saved_libras[0].read_bytes() == b"libras-alibras-b"
    assert saved_ad[0].read_bytes() == b"ad-aad-b"


# â”€â”€ Video Detail â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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


# â”€â”€ Reprocess â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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


# â”€â”€ Delete â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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


# â”€â”€ Docs â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def test_docs_page(auth_client):
    r = auth_client.get("/admin/docs")
    assert r.status_code == 200
    assert "Documentação" in r.text
    assert "Tutorial" in r.text


def test_docs_requires_auth(client):
    r = client.get("/admin/docs", follow_redirects=False)
    assert r.status_code == 401


# â”€â”€ DB-based login â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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


# â”€â”€ Video Status API â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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


def test_update_video_metadata_only(auth_client, tmp_path, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "storage_dir", tmp_path / "weplayer")

    main_input = tmp_path / "weplayer" / "videos" / "vid-upd-1" / "input" / "main.mp4"
    main_input.parent.mkdir(parents=True)
    main_input.write_bytes(b"fake")

    db = TestingSessionLocal()
    v = Video(id="vid-upd-1", title="Old", description="Old desc", status=VideoStatus.ready)
    db.add(v)
    db.add(VideoAsset(
        id=str(uuid.uuid4()),
        video_id="vid-upd-1",
        asset_type=AssetType.original_input,
        file_path=str(main_input),
        status=AssetStatus.ready,
    ))
    db.commit()
    db.close()

    r = auth_client.post(
        "/admin/videos/vid-upd-1/update",
        data={"title": "Novo titulo", "description": "Nova descricao"},
    )
    assert r.status_code == 200

    db = TestingSessionLocal()
    v = db.query(Video).get("vid-upd-1")
    assert v.title == "Novo titulo"
    assert v.description == "Nova descricao"
    assert v.status == VideoStatus.ready
    db.close()


def test_update_video_with_new_main_triggers_reprocess(auth_client, tmp_path, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "storage_dir", tmp_path / "weplayer")

    old_main = tmp_path / "weplayer" / "videos" / "vid-upd-2" / "input" / "main.mp4"
    old_main.parent.mkdir(parents=True)
    old_main.write_bytes(b"old")

    db = TestingSessionLocal()
    v = Video(id="vid-upd-2", title="Old", status=VideoStatus.ready)
    db.add(v)
    db.add(VideoAsset(
        id=str(uuid.uuid4()),
        video_id="vid-upd-2",
        asset_type=AssetType.original_input,
        file_path=str(old_main),
        status=AssetStatus.ready,
    ))
    db.commit()
    db.close()

    with patch("app.routes.admin._process_video"):
        r = auth_client.post(
            "/admin/videos/vid-upd-2/update",
            data={"title": "Com novo video", "description": ""},
            files=[_fake_file("video_file", "novo.mp4", b"new-main", "video/mp4")],
        )
    assert r.status_code == 200

    db = TestingSessionLocal()
    v = db.query(Video).get("vid-upd-2")
    assert v.status == VideoStatus.pending
    assert v.title == "Com novo video"
    db.close()


def test_update_video_invalid_cover_extension(auth_client):
    db = TestingSessionLocal()
    v = make_video(db, status=VideoStatus.ready)
    vid_id = v.id
    db.close()

    r = auth_client.post(
        f"/admin/videos/{vid_id}/update",
        data={"title": "X", "description": ""},
        files=[_fake_file("cover_file", "bad.gif", b"gifdata", "image/gif")],
    )
    assert r.status_code == 422
    assert "capa invalido" in r.text

def test_update_video_with_all_optional_assets(auth_client, tmp_path, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "storage_dir", tmp_path / "weplayer")

    old_main = tmp_path / "weplayer" / "videos" / "vid-upd-3" / "input" / "main.mp4"
    old_main.parent.mkdir(parents=True)
    old_main.write_bytes(b"old")

    db = TestingSessionLocal()
    v = Video(id="vid-upd-3", title="Old", status=VideoStatus.ready)
    db.add(v)
    db.add(VideoAsset(
        id=str(uuid.uuid4()),
        video_id="vid-upd-3",
        asset_type=AssetType.original_input,
        file_path=str(old_main),
        status=AssetStatus.ready,
    ))
    db.commit()
    db.close()

    with patch("app.routes.admin._process_video"):
        r = auth_client.post(
            "/admin/videos/vid-upd-3/update",
            data={"title": "Full update", "description": "desc"},
            files=[
                _fake_file("libras_file", "libras.mp4", b"l", "video/mp4"),
                _fake_file("ad_file", "ad.mp3", b"a", "audio/mpeg"),
                _fake_file("subtitle_file", "sub.srt", b"1", "text/plain"),
                _fake_file("cover_file", "cover.jpg", b"img", "image/jpeg"),
            ],
        )
    assert r.status_code == 200

    db = TestingSessionLocal()
    v = db.query(Video).get("vid-upd-3")
    assert v.status == VideoStatus.pending
    assert v.cover_path is not None
    db.close()


def test_update_video_reprocess_without_main_returns_400(auth_client, tmp_path, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "storage_dir", tmp_path / "weplayer")

    db = TestingSessionLocal()
    v = Video(id="vid-upd-4", title="Old", status=VideoStatus.ready)
    db.add(v)
    db.commit()
    db.close()

    r = auth_client.post(
        "/admin/videos/vid-upd-4/update",
        data={"title": "No main", "description": ""},
        files=[_fake_file("libras_file", "libras.mp4", b"l", "video/mp4")],
    )
    assert r.status_code == 400
    assert "Nao foi possivel localizar" in r.text
