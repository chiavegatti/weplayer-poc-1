import threading
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request, UploadFile, File, BackgroundTasks, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
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

# Max 1 FFmpeg job at a time â€” protects the server under concurrent uploads
_encode_semaphore = threading.Semaphore(1)

CHUNKABLE_FIELDS = {
    "video_file": storage.ALLOWED_VIDEO_EXTENSIONS,
    "libras_file": storage.ALLOWED_VIDEO_EXTENSIONS,
    "ad_file": storage.ALLOWED_AUDIO_EXTENSIONS,
}


async def _save_uploaded_asset(
    upload_file: UploadFile | None,
    chunk_upload_id: str | None,
    chunk_total: int | None,
    chunk_filename: str | None,
    allowed_extensions: set[str],
    destination: Path,
    invalid_message: str,
) -> Path | None:
    upload_filename = (upload_file.filename if upload_file else chunk_filename) or ""
    if not upload_filename:
        return None

    if not storage.validate_extension(upload_filename, allowed_extensions):
        raise ValueError(invalid_message)

    if upload_file is not None:
        await save_upload(upload_file, destination)
        return destination

    if not chunk_upload_id or not chunk_total:
        raise ValueError("Upload em chunks incompleto.")

    try:
        return storage.assemble_upload_chunks(chunk_upload_id, destination, chunk_total)
    except FileNotFoundError:
        storage.cleanup_multipart_upload(chunk_upload_id)
        raise ValueError("Upload em chunks incompleto.")


# â”€â”€â”€ Auth â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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
            {"request": request, "error": "UsuÃ¡rio ou senha invÃ¡lidos."},
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


# â”€â”€â”€ Dashboard â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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


# â”€â”€â”€ Docs â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@router.get("/docs", response_class=HTMLResponse)
def admin_docs(
    request: Request,
    _admin: str = Depends(get_current_admin),
):
    return templates.TemplateResponse(
        "admin/docs.html", {"request": request, "admin": _admin}
    )


# â”€â”€â”€ New Video â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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
    video_chunk_upload_id: str | None = Form(None),
    video_chunk_total: int | None = Form(None),
    video_chunk_filename: str | None = Form(None),
    libras_chunk_upload_id: str | None = Form(None),
    libras_chunk_total: int | None = Form(None),
    libras_chunk_filename: str | None = Form(None),
    ad_chunk_upload_id: str | None = Form(None),
    ad_chunk_total: int | None = Form(None),
    ad_chunk_filename: str | None = Form(None),
    video_file: UploadFile | None = File(None),
    libras_file: UploadFile | None = File(None),
    ad_file: UploadFile | None = File(None),
    subtitle_file: UploadFile | None = File(None),
    cover_file: UploadFile | None = File(None),
    db: Session = Depends(get_db),
    _admin: str = Depends(get_current_admin),
):
    video_id = str(uuid.uuid4())
    try:
        main_filename = (video_file.filename if video_file else video_chunk_filename) or ""
        if not main_filename:
            raise ValueError("Envie o vídeo principal para continuar.")
        main_dest = await _save_uploaded_asset(
            video_file,
            video_chunk_upload_id,
            video_chunk_total,
            video_chunk_filename,
            storage.ALLOWED_VIDEO_EXTENSIONS,
            storage.get_input_path(video_id, f"main{Path(main_filename).suffix}"),
            "Arquivo de vídeo inválido. Use MP4, MOV, AVI, MKV ou WEBM.",
        )
        if main_dest is None:
            raise ValueError("Envie o vídeo principal para continuar.")

        libras_filename = (libras_file.filename if libras_file else libras_chunk_filename) or ""
        libras_path = await _save_uploaded_asset(
            libras_file,
            libras_chunk_upload_id,
            libras_chunk_total,
            libras_chunk_filename,
            storage.ALLOWED_VIDEO_EXTENSIONS,
            storage.get_input_path(video_id, f"libras{Path(libras_filename).suffix}") if libras_filename else Path(),
            "Vídeo de Libras inválido. Use MP4, MOV, AVI, MKV ou WEBM.",
        )

        ad_filename = (ad_file.filename if ad_file else ad_chunk_filename) or ""
        ad_path = await _save_uploaded_asset(
            ad_file,
            ad_chunk_upload_id,
            ad_chunk_total,
            ad_chunk_filename,
            storage.ALLOWED_AUDIO_EXTENSIONS,
            storage.get_input_path(video_id, f"ad{Path(ad_filename).suffix}") if ad_filename else Path(),
            "Arquivo de audiodescrição inválido. Use MP3, AAC, WAV, OGG ou M4A.",
        )

    except ValueError as exc:
        return templates.TemplateResponse(
            "admin/video_form.html",
            {"request": request, "error": str(exc)},
            status_code=422,
        )

    subtitle_path: Path | None = None
    cover_path: Path | None = None

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


@router.post("/uploads/initiate")
def initiate_upload(
    field_name: str = Form(...),
    filename: str = Form(...),
    _admin: str = Depends(get_current_admin),
):
    allowed_extensions = CHUNKABLE_FIELDS.get(field_name)
    if not allowed_extensions:
        raise HTTPException(status_code=422, detail="Campo de upload inválido.")
    if not storage.validate_extension(filename, allowed_extensions):
        raise HTTPException(status_code=422, detail="Arquivo incompatível com o campo informado.")

    upload_id = str(uuid.uuid4())
    storage.get_multipart_dir(upload_id).mkdir(parents=True, exist_ok=True)
    return JSONResponse(
        {
            "upload_id": upload_id,
            "chunk_size": storage.UPLOAD_CHUNK_SIZE,
        }
    )


@router.post("/uploads/{upload_id}/chunk")
async def upload_chunk(
    upload_id: str,
    chunk_index: int = Form(...),
    chunk: UploadFile = File(...),
    _admin: str = Depends(get_current_admin),
):
    if chunk_index < 0:
        raise HTTPException(status_code=422, detail="Chunk inválido.")
    await storage.save_upload_chunk(upload_id, chunk_index, chunk)
    return JSONResponse({"ok": True, "chunk_index": chunk_index})


def _add_asset(db: Session, video_id: str, asset_type: AssetType, path: Path) -> VideoAsset:
    asset = VideoAsset(
        video_id=video_id,
        asset_type=asset_type,
        file_path=str(path),
        status=AssetStatus.ready,
    )
    db.add(asset)
    return asset


# â”€â”€â”€ Video Status JSON â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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


# â”€â”€â”€ Video Detail â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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
        {"request": request, "video": video, "logs": log_content, "update_error": None},
    )


@router.post("/videos/{video_id}/reprocess")
def reprocess_video(
    video_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    _admin: str = Depends(get_current_admin),
):
    video = _get_video_or_404(db, video_id)

    main_input = _get_input_path_from_assets(video, AssetType.original_input)
    if not main_input:
        raise HTTPException(status_code=400, detail="VÃ­deo original nÃ£o encontrado no storage.")

    video.status = VideoStatus.pending
    video.error_message = None
    db.commit()

    background_tasks.add_task(
        _process_video,
        video_id=video_id,
        main_input=main_input,
        libras_input=_get_input_path_from_assets(video, AssetType.libras_input),
        ad_input=_get_input_path_from_assets(video, AssetType.ad_input),
        subtitle_input=_get_input_path_from_assets(video, AssetType.subtitle_input),
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


@router.post("/videos/{video_id}/update")
async def update_video(
    video_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    title: str = Form(...),
    description: str = Form(""),
    video_file: UploadFile | None = File(None),
    libras_file: UploadFile | None = File(None),
    ad_file: UploadFile | None = File(None),
    subtitle_file: UploadFile | None = File(None),
    cover_file: UploadFile | None = File(None),
    db: Session = Depends(get_db),
    _admin: str = Depends(get_current_admin),
):
    video = _get_video_or_404(db, video_id)

    def _invalid_file(upload: UploadFile | None, allowed: set[str]) -> bool:
        return bool(upload and upload.filename and not storage.validate_extension(upload.filename, allowed))

    if _invalid_file(video_file, storage.ALLOWED_VIDEO_EXTENSIONS):
        return _video_detail_with_error(
            request, video, "Arquivo de video principal invalido.", db, status_code=422
        )
    if _invalid_file(libras_file, storage.ALLOWED_VIDEO_EXTENSIONS):
        return _video_detail_with_error(
            request, video, "Arquivo de Libras invalido.", db, status_code=422
        )
    if _invalid_file(ad_file, storage.ALLOWED_AUDIO_EXTENSIONS):
        return _video_detail_with_error(
            request, video, "Arquivo de audiodescricao invalido.", db, status_code=422
        )
    if _invalid_file(subtitle_file, storage.ALLOWED_SUBTITLE_EXTENSIONS):
        return _video_detail_with_error(
            request, video, "Arquivo de legenda invalido.", db, status_code=422
        )
    if _invalid_file(cover_file, storage.ALLOWED_IMAGE_EXTENSIONS):
        return _video_detail_with_error(
            request, video, "Arquivo de capa invalido.", db, status_code=422
        )

    video.title = title.strip()
    video.description = description.strip() or None

    main_input = _get_input_path_from_assets(video, AssetType.original_input)
    libras_input = _get_input_path_from_assets(video, AssetType.libras_input)
    ad_input = _get_input_path_from_assets(video, AssetType.ad_input)
    subtitle_input = _get_input_path_from_assets(video, AssetType.subtitle_input)
    needs_reprocess = False

    if video_file and video_file.filename:
        main_input = storage.get_input_path(video_id, f"main{Path(video_file.filename).suffix}")
        await save_upload(video_file, main_input)
        _set_input_asset_path(db, video_id, AssetType.original_input, main_input)
        needs_reprocess = True

    if libras_file and libras_file.filename:
        libras_input = storage.get_input_path(video_id, f"libras{Path(libras_file.filename).suffix}")
        await save_upload(libras_file, libras_input)
        _set_input_asset_path(db, video_id, AssetType.libras_input, libras_input)
        needs_reprocess = True

    if ad_file and ad_file.filename:
        ad_input = storage.get_input_path(video_id, f"ad{Path(ad_file.filename).suffix}")
        await save_upload(ad_file, ad_input)
        _set_input_asset_path(db, video_id, AssetType.ad_input, ad_input)
        needs_reprocess = True

    if subtitle_file and subtitle_file.filename:
        subtitle_input = storage.get_input_path(video_id, f"subtitle{Path(subtitle_file.filename).suffix}")
        await save_upload(subtitle_file, subtitle_input)
        _set_input_asset_path(db, video_id, AssetType.subtitle_input, subtitle_input)
        needs_reprocess = True

    if cover_file and cover_file.filename:
        cover_path = storage.get_cover_path(video_id, f"cover{Path(cover_file.filename).suffix}")
        await save_upload(cover_file, cover_path)
        video.cover_path = storage.get_relative_media_path(cover_path)

    if needs_reprocess:
        if not main_input or not main_input.exists():
            return _video_detail_with_error(
                request, video, "Nao foi possivel localizar o video principal para reprocessar.", db, status_code=400
            )
        video.status = VideoStatus.pending
        video.error_message = None
        video.libras_available = False
        video.ad_available = False
        video.subtitle_available = False
        db.commit()

        background_tasks.add_task(
            _process_video,
            video_id=video_id,
            main_input=main_input,
            libras_input=libras_input,
            ad_input=ad_input,
            subtitle_input=subtitle_input,
        )
        return RedirectResponse(url=f"/admin/videos/{video_id}?updated=1&reprocess=1", status_code=302)

    db.commit()
    return RedirectResponse(url=f"/admin/videos/{video_id}?updated=1", status_code=302)


# â”€â”€â”€ Background processing â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _process_video(
    video_id: str,
    main_input: Path,
    libras_input: Path | None,
    ad_input: Path | None,
    subtitle_input: Path | None,
    _session_factory=None,
) -> None:
    """Synchronous processing job â€” runs in BackgroundTasks thread."""
    from app.database import SessionLocal
    from app.services import ffmpeg_service as ffmpeg

    session_factory = _session_factory or SessionLocal

    # Wait for the semaphore â€” video stays 'pending' while queued
    with _encode_semaphore:
        db = session_factory()
        try:
            video = db.query(Video).get(video_id)
            if not video:
                return

            video.status = VideoStatus.processing
            db.commit()

            results = {}
            normalized_main = main_input
            normalized_libras = libras_input

            # Always normalize main source before HLS generation.
            try:
                normalized_main = ffmpeg.preprocess_main_input(video_id, main_input)
                _set_input_asset_path(db, video_id, AssetType.original_input, normalized_main)
                if main_input != normalized_main and main_input.exists():
                    main_input.unlink()
            except Exception as exc:
                _fail_video(db, video_id, f"Erro na normalizacao do video principal: {exc}")
                return

            # Always normalize Libras source before overlay processing.
            if libras_input:
                try:
                    normalized_libras = ffmpeg.preprocess_libras_input(video_id, libras_input)
                    _set_input_asset_path(db, video_id, AssetType.libras_input, normalized_libras)
                    if libras_input != normalized_libras and libras_input.exists():
                        libras_input.unlink()
                except Exception as exc:
                    _upsert_asset(db, video_id, AssetType.hls_libras, None, error=str(exc))
                    normalized_libras = None

            # Original HLS
            try:
                manifest = ffmpeg.process_original_hls(video_id, normalized_main)
                _upsert_asset(db, video_id, AssetType.hls_original, manifest)
                results["original"] = True
            except Exception as exc:
                _fail_video(db, video_id, f"Erro no original: {exc}")
                return

            # Libras HLS
            if normalized_libras:
                try:
                    manifest = ffmpeg.process_libras_hls(
                        video_id,
                        normalized_main,
                        normalized_libras,
                        pre_normalized=True,
                    )
                    _upsert_asset(db, video_id, AssetType.hls_libras, manifest)
                    results["libras"] = True
                except Exception as exc:
                    _upsert_asset(db, video_id, AssetType.hls_libras, None, error=str(exc))

            # AD HLS
            if ad_input:
                try:
                    manifest = ffmpeg.process_ad_hls(video_id, normalized_main, ad_input)
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

            # Auto-thumbnail fallback when cover is not provided.
            if not video.cover_path:
                try:
                    thumb_path = ffmpeg.extract_thumbnail(video_id, normalized_main)
                    video.cover_path = storage.get_relative_media_path(thumb_path)
                except Exception:
                    pass

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


def _set_input_asset_path(db: Session, video_id: str, asset_type: AssetType, path: Path) -> None:
    asset = db.query(VideoAsset).filter_by(video_id=video_id, asset_type=asset_type).first()
    if not asset:
        asset = VideoAsset(video_id=video_id, asset_type=asset_type)
        db.add(asset)
    asset.file_path = str(path)
    asset.status = AssetStatus.ready
    asset.error_message = None
    db.commit()


def _get_input_path_from_assets(video: Video, asset_type: AssetType) -> Path | None:
    for asset in video.assets:
        if asset.asset_type == asset_type and asset.file_path:
            p = storage.resolve_media_path(asset.file_path)
            if p and p.exists():
                return p
    return None


def _video_detail_with_error(
    request: Request,
    video: Video,
    message: str,
    db: Session,
    status_code: int,
):
    db.refresh(video)
    return templates.TemplateResponse(
        "admin/video_detail.html",
        {
            "request": request,
            "video": video,
            "logs": _read_logs(video.id),
            "update_error": message,
        },
        status_code=status_code,
    )


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
        raise HTTPException(status_code=404, detail="VÃ­deo nÃ£o encontrado.")
    return video


def _read_logs(video_id: str) -> dict:
    logs = {}
    log_dir = settings.video_logs_dir(video_id)
    if log_dir.exists():
        for log_file in log_dir.glob("*.log"):
            logs[log_file.stem] = log_file.read_text(encoding="utf-8", errors="replace")
    return logs
