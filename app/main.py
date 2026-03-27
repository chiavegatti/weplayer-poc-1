from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.database import init_db, SessionLocal
from app.auth import hash_password

BASE_DIR = Path(__file__).parent

SEED_ADMIN_EMAIL = "iguale@iguale.com.br"
SEED_ADMIN_PASSWORD = "acesso10@123"


def _seed_admin_user() -> None:
    """Create the default admin user if it doesn't exist yet."""
    from app.models.models import AdminUser
    db = SessionLocal()
    try:
        exists = db.query(AdminUser).filter(AdminUser.email == SEED_ADMIN_EMAIL).first()
        if not exists:
            user = AdminUser(
                email=SEED_ADMIN_EMAIL,
                hashed_password=hash_password(SEED_ADMIN_PASSWORD),
            )
            db.add(user)
            db.commit()
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    settings.videos_dir.mkdir(parents=True, exist_ok=True)
    init_db()
    _seed_admin_user()
    yield
    # Shutdown (nothing to clean for POC)


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    debug=settings.debug,
    lifespan=lifespan,
)

# Static files
app.mount("/static", StaticFiles(directory=BASE_DIR.parent / "static"), name="static")

# Serve HLS files from storage
storage_path = settings.storage_dir
if storage_path.exists():
    app.mount("/media", StaticFiles(directory=storage_path), name="media")

# Templates
templates = Jinja2Templates(directory=BASE_DIR / "templates")

# Import and register routers
from app.routes.admin import router as admin_router  # noqa: E402
from app.routes.catalog import router as catalog_router  # noqa: E402
from app.routes.api import router as api_router  # noqa: E402

app.include_router(admin_router, prefix="/admin", tags=["admin"])
app.include_router(catalog_router, tags=["public"])
app.include_router(api_router, prefix="/api", tags=["api"])


@app.get("/health")
def health_check():
    return {"status": "ok", "app": settings.app_name, "version": settings.app_version}
