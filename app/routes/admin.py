import threading
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request, UploadFile, File, BackgroundTasks, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.auth import check_credentials, create_session_token, get_current_admin
from app.config import settings
from app.database import get_db
from app.models.models import Video, VideoAsset, VideoStatus, AssetType, AssetStatus
from app.services import storage_service as storage
from app.services.storage_service import save_upload

BASE_DIR = Path(__file__).parent.parent
templates = Jinja2Templates(directory=BASE_DIR / "templates")

router = APIRouter()

# Max 1 FFmpeg job at a time — protects the server under concurrent uploads
_encode_semaphore = threading.Semaphore(1)


# ─── Auth ────────────────────────────────────────────────────────────────────

@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("admin/login.html", {"request": request, "error": None})


@router.post("/login")
def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    if not check_credentials(username, password, db):
        return templates.TemplateResponse(
            "admin/login.html",
            {"request": request, "error": "Usuário ou senha inválidos."},
            status_code=401,
        )
    token = create_session_token(username)
    response = RedirectResponse(url="/admin/dashboard", status_code=302)
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        httponly=True,
        max_age=settings.session_max_age,
        samesite="lax",
    )
    return response


@router.get("/logout")
def logout():
    response = RedirectResponse(url="/admin/login", status_code=302)
    response.delete_cookie(settings.session_cookie_name)
    return response


# ─── Dashboard ───────────────────────────────────────────────────────────────

@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(
    request: Request,
    db: Session = Depends(get_db),
    _admin: str = Depends(get_current_admin),
):
    videos = db.query(Video).order_by(Video.created_at.desc()).all()
    return templates.TemplateResponse(
        "admin/dashboard.html", {"request": request, "videos": videos, "admin": _admin}
    )


# ─── Docs ─────────────────────────────────────────────────────────────────────

@router.get("/docs", response_class=HTMLResponse)
def admin_docs(
    request: Request,
    _admin: str = Depends(get_current_admin),
):
    return templates.TemplateResponse(
        "admin/docs.html", {"request": request, "admin": _admin}
    )


# ─── New Video ───────────────────────────────────────────────────────────────

@router.get("/videos/new", response_class=HTMLResponse)
def new_video_form(
    request: Request,
    _admin: str = Depends(get_current_admin),
):
    return templates.TemplateResponse("admin/video_form.html", {"request": request, "error": None})


@router.post("/videos/new")
async def create_video(
    request: Request,
    background_tasks: BackgroundTasks,
    title: str = Form(...),
    description: str = Form(""),
    video_file: UploadFile = File(...),
    libras_file: UploadFile | None = File(None),
    ad_file: UploadFile | None = File(None),
    subtitle_file: UploadFile | None = File(None),
    cover_file: UploadFile | None = File(None),
    db: Session = Depends(get_db),
    _admin: str = Depends(get_current_admin),
):
    # Validate main video
    if not storage.validate_extension(video_file.filename or "", storage.ALLOWED_VIDEO_EXTENSIONS):
        return templates.TemplateResponse(
            "admin/video_form.html",
            {"request": request, "error": "Arquivo de vídeo inválido. Use MP4, MOV, AVI, MKV ou WEBM."},
            status_code=422,
        )

    video_id = str(uuid.uuid4())

    # Save main video
    main_dest = storage.get_input_path(video_id, f"main{Path(video_file.filename or '.mp4').suffix}")
    await save_upload(video_file, main_dest)

    # Optional assets
    libras_path: Path | None = None
    ad_path: Path | None = None
    subtitle_path: Path | None = None
    cover_path: Path | None = None

    if libras_file and libras_file.filename:
        if storage.validate_extension(libras_file.filename, storage.ALLOWED_VIDEO_EXTENSIONS):
            libras_path = storage.get_input_path(
                video_id, f"libras{Path(libras_file.filename).suffix}"
            )
            await save_upload(libras_file, libras_path)

    if ad_file and ad_file.filename:
        if storage.validate_extension(ad_file.filename, storage.ALLOWED_AUDIO_EXTENSIONS):
            ad_path = storage.get_input_path(video_id, f"ad{Path(ad_file.filename).suffix}")
            await save_upload(ad_file, ad_path)

    if subtitle_file and subtitle_file.filename:
        if storage.validate_extension(subtitle_file.filename, storage.ALLOWED_SUBTITLE_EXTENSIONS):
            subtitle_path = storage.get_input_path(
                video_id, f"subtitle{Path(subtitle_file.filename).suffix}"
            )
            await save_upload(subtitle_file, subtitle_path)

    if cover_file and cover_file.filename:
        if storage.validate_extension(cover_file.filename, storage.ALLOWED_IMAGE_EXTENSIONS):
            cover_path = storage.get_cover_path(
                video_id, f"cover{Path(cover_file.filename).suffix}"
            )
            await save_upload(cover_file, cover_path)

    # Create Video record
    cover_rel = storage.get_relative_media_path(cover_path) if cover_path else None
    video = Video(
        id=video_id,
        title=title,
        description=description or None,
        cover_path=cover_rel,
        status=VideoStatus.pending,
    )
    db.add(video)

    # Create input asset records
    _add_asset(db, video_id, AssetType.original_input, main_dest)
    if libras_path:
        _add_asset(db, video_id, AssetType.libras_input, libras_path)
    if ad_path:
        _add_asset(db, video_id, AssetType.ad_input, ad_path)
    if subtitle_path:
        _add_asset(db, video_id, AssetType.subtitle_input, subtitle_path)

    db.commit()

    # Kick off background processing
    background_tasks.add_task(
        _process_video,
        video_id=video_id,
        main_input=main_dest,
        libras_input=libras_path,
        ad_input=ad_path,
        subtitle_input=subtitle_path,
    )

    return RedirectResponse(url="/admin/dashboard?uploaded=1", status_code=302)


def _add_asset(db: Session, video_id: str, asset_type: AssetType, path: Path) -> VideoAsset:
    asset = VideoAsset(
        video_id=video_id,
        asset_type=asset_type,
        file_path=str(path),
        status=AssetStatus.ready,
    )
    db.add(asset)
    return asset


# ─── Video Status JSON ────────────────────────────────────────────────────────

@router.get("/videos/{video_id}/status")
def video_status_api(
    video_id: str,
    db: Session = Depends(get_db),
    _admin: str = Depends(get_current_admin),
):
    from fastapi.responses import JSONResponse
    v = db.query(Video).filter(Video.id == video_id).first()
    if not v:
        raise HTTPException(status_code=404, detail="Not found")
    # Count stages: each input asset corresponds to one output stage
    input_types = {AssetType.original_input, AssetType.libras_input, AssetType.ad_input, AssetType.subtitle_input}
    output_types = {AssetType.hls_original, AssetType.hls_libras, AssetType.hls_ad, AssetType.subtitle_vtt}
    stages_total = sum(1 for a in v.assets if a.asset_type in input_types)
    stages_done = sum(1 for a in v.assets if a.asset_type in output_types and a.status.value == "ready")

    # Queue position: how many pending/processing videos were created before this one
    queue_position = None
    if v.status == VideoStatus.pending:
        queue_position = (
            db.query(Video)
            .filter(Video.status.in_([VideoStatus.pending, VideoStatus.processing]))
            .filter(Video.created_at < v.created_at)
            .count()
        ) + 1

    return JSONResponse({
        "id": v.id,
        "status": v.status.value,
        "title": v.title,
        "updated_at": v.updated_at.isoformat() if v.updated_at else None,
        "stages_done": stages_done,
        "stages_total": max(stages_total, 1),
        "queue_position": queue_position,
    })


# ─── Video Detail ─────────────────────────────────────────────────────────────

@router.get("/videos/{video_id}", response_class=HTMLResponse)
def video_detail(
    video_id: str,
    request: Request,
    db: Session = Depends(get_db),
    _admin: str = Depends(get_current_admin),
):
    video = _get_video_or_404(db, video_id)
    log_content = _read_logs(video_id)
    return templates.TemplateResponse(
        "admin/video_detail.html",
        {"request": request, "video": video, "logs": log_content},
    )


@router.post("/videos/{video_id}/reprocess")
def reprocess_video(
    video_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    _admin: str = Depends(get_current_admin),
):
    video = _get_video_or_404(db, video_id)

    def _get_input_path(asset_type: AssetType) -> Path | None:
        for a in video.assets:
            if a.asset_type == asset_type and a.file_path:
                p = Path(a.file_path)
                return p if p.exists() else None
        return None

    main_input = _get_input_path(AssetType.original_input)
    if not main_input:
        raise HTTPException(status_code=400, detail="Vídeo original não encontrado no storage.")

    video.status = VideoStatus.pending
    video.error_message = None
    db.commit()

    background_tasks.add_task(
        _process_video,
        video_id=video_id,
        main_input=main_input,
        libras_input=_get_input_path(AssetType.libras_input),
        ad_input=_get_input_path(AssetType.ad_input),
        subtitle_input=_get_input_path(AssetType.subtitle_input),
    )
    return RedirectResponse(url=f"/admin/videos/{video_id}", status_code=302)


@router.post("/videos/{video_id}/delete")
def delete_video(
    video_id: str,
    db: Session = Depends(get_db),
    _admin: str = Depends(get_current_admin),
):
    video = _get_video_or_404(db, video_id)
    storage.delete_video_storage(video_id)
    db.delete(video)
    db.commit()
    return RedirectResponse(url="/admin/dashboard", status_code=302)


# ─── Background processing ───────────────────────────────────────────────────

def _process_video(
    video_id: str,
    main_input: Path,
    libras_input: Path | None,
    ad_input: Path | None,
    subtitle_input: Path | None,
    _session_factory=None,
) -> None:
    """Synchronous processing job — runs in BackgroundTasks thread."""
    from app.database import SessionLocal
    from app.services import ffmpeg_service as ffmpeg

    session_factory = _session_factory or SessionLocal

    # Wait for the semaphore — video stays 'pending' while queued
    with _encode_semaphore:
        db = session_factory()
        try:
            video = db.query(Video).get(video_id)
            if not video:
                return

            video.status = VideoStatus.processing
            db.commit()

            results = {}

            # Original HLS
            try:
                manifest = ffmpeg.process_original_hls(video_id, main_input)
                _upsert_asset(db, video_id, AssetType.hls_original, manifest)
                results["original"] = True
            except Exception as exc:
                _fail_video(db, video_id, f"Erro no original: {exc}")
                return

            # Libras HLS
            if libras_input:
                try:
                    manifest = ffmpeg.process_libras_hls(video_id, main_input, libras_input)
                    _upsert_asset(db, video_id, AssetType.hls_libras, manifest)
                    results["libras"] = True
                except Exception as exc:
                    _upsert_asset(db, video_id, AssetType.hls_libras, None, error=str(exc))

            # AD HLS
            if ad_input:
                try:
                    manifest = ffmpeg.process_ad_hls(video_id, main_input, ad_input)
                    _upsert_asset(db, video_id, AssetType.hls_ad, manifest)
                    results["ad"] = True
                except Exception as exc:
                    _upsert_asset(db, video_id, AssetType.hls_ad, None, error=str(exc))

            # Subtitle VTT
            if subtitle_input:
                try:
                    vtt_path = ffmpeg.process_subtitle_vtt(video_id, subtitle_input)
                    _upsert_asset(db, video_id, AssetType.subtitle_vtt, vtt_path)
                    results["subtitle"] = True
                except Exception as exc:
                    _upsert_asset(db, video_id, AssetType.subtitle_vtt, None, error=str(exc))

            # Refresh video object and update flags
            db.expire(video)
            video = db.query(Video).get(video_id)
            video.status = VideoStatus.ready
            video.libras_available = results.get("libras", False)
            video.ad_available = results.get("ad", False)
            video.subtitle_available = results.get("subtitle", False)
            db.commit()

        except Exception as exc:
            _fail_video(db, video_id, str(exc))
        finally:
            db.close()


def _upsert_asset(
    db: Session,
    video_id: str,
    asset_type: AssetType,
    path: Path | None,
    error: str | None = None,
) -> None:
    asset = (
        db.query(VideoAsset)
        .filter_by(video_id=video_id, asset_type=asset_type)
        .first()
    )
    if not asset:
        asset = VideoAsset(video_id=video_id, asset_type=asset_type)
        db.add(asset)

    if path:
        asset.file_path = storage.get_relative_media_path(path)
        asset.status = AssetStatus.ready
        asset.error_message = None
    else:
        asset.status = AssetStatus.error
        asset.error_message = error
    db.commit()


def _fail_video(db: Session, video_id: str, message: str) -> None:
    video = db.query(Video).get(video_id)
    if video:
        video.status = VideoStatus.error
        video.error_message = message
        db.commit()


def _get_video_or_404(db: Session, video_id: str) -> Video:
    video = db.query(Video).get(video_id)
    if not video:
        raise HTTPException(status_code=404, detail="Vídeo não encontrado.")
    return video


def _read_logs(video_id: str) -> dict:
    logs = {}
    log_dir = settings.video_logs_dir(video_id)
    if log_dir.exists():
        for log_file in log_dir.glob("*.log"):
            logs[log_file.stem] = log_file.read_text(encoding="utf-8", errors="replace")
    return logs
