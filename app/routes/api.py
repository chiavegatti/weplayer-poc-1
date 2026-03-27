from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import get_current_admin
from app.database import get_db
from app.models.models import Video, VideoStatus
from app.schemas.video import VideoOut

router = APIRouter()


@router.get("/videos", response_model=list[VideoOut])
def list_videos(
    db: Session = Depends(get_db),
    _admin: str = Depends(get_current_admin),
):
    return db.query(Video).order_by(Video.created_at.desc()).all()


@router.get("/videos/{video_id}", response_model=VideoOut)
def get_video(
    video_id: str,
    db: Session = Depends(get_db),
    _admin: str = Depends(get_current_admin),
):
    video = db.query(Video).get(video_id)
    if not video:
        raise HTTPException(status_code=404, detail="Vídeo não encontrado.")
    return video


@router.get("/public/videos", response_model=list[VideoOut])
def list_public_videos(db: Session = Depends(get_db)):
    return (
        db.query(Video)
        .filter(Video.status == VideoStatus.ready)
        .order_by(Video.created_at.desc())
        .all()
    )
