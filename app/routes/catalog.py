from pathlib import Path

from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import Video, VideoStatus

BASE_DIR = Path(__file__).parent.parent
templates = Jinja2Templates(directory=BASE_DIR / "templates")

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse("public/index.html", {"request": request})


@router.get("/catalog", response_class=HTMLResponse)
def catalog(request: Request, db: Session = Depends(get_db)):
    videos = (
        db.query(Video)
        .filter(Video.status == VideoStatus.ready)
        .order_by(Video.created_at.desc())
        .all()
    )
    return templates.TemplateResponse(
        "public/catalog.html", {"request": request, "videos": videos}
    )


@router.get("/watch/{video_id}", response_class=HTMLResponse)
def watch(video_id: str, request: Request, db: Session = Depends(get_db)):
    video = db.query(Video).get(video_id)
    if not video or video.status != VideoStatus.ready:
        raise HTTPException(status_code=404, detail="VÃ­deo nÃ£o encontrado.")

    manifests = {
        "original": video.get_hls_manifest("original"),
        "libras": video.get_hls_manifest("libras"),
        "ad": video.get_hls_manifest("ad"),
    }
    subtitle_path = video.get_subtitle_path()

    return templates.TemplateResponse(
        "public/player.html",
        {
            "request": request,
            "video": video,
            "manifests": manifests,
            "subtitle_path": subtitle_path,
        },
    )
