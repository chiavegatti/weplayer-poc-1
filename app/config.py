import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent.parent


class Settings:
    app_name: str = "WePlayer"
    app_version: str = "0.1.0"

    admin_username: str = os.getenv("ADMIN_USERNAME", "admin")
    admin_password: str = os.getenv("ADMIN_PASSWORD", "admin123")
    secret_key: str = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")

    database_url: str = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR}/weplayer.db")

    storage_dir: Path = Path(os.getenv("STORAGE_DIR", str(BASE_DIR / "storage" / "weplayer")))

    debug: bool = os.getenv("DEBUG", "true").lower() == "true"

    # Session cookie config
    session_cookie_name: str = "weplayer_session"
    session_max_age: int = 60 * 60 * 8  # 8 hours

    @property
    def videos_dir(self) -> Path:
        return self.storage_dir / "videos"

    def video_dir(self, video_id: str) -> Path:
        return self.videos_dir / video_id

    def video_input_dir(self, video_id: str) -> Path:
        return self.video_dir(video_id) / "input"

    def video_processed_dir(self, video_id: str, variant: str) -> Path:
        return self.video_dir(video_id) / "processed" / variant

    def video_subtitles_dir(self, video_id: str) -> Path:
        return self.video_dir(video_id) / "subtitles"

    def video_covers_dir(self, video_id: str) -> Path:
        return self.video_dir(video_id) / "covers"

    def video_logs_dir(self, video_id: str) -> Path:
        return self.video_dir(video_id) / "logs"


settings = Settings()
