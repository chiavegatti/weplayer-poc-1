import bcrypt as _bcrypt

from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from fastapi import Request, HTTPException
from sqlalchemy.orm import Session

from app.config import settings

_serializer = URLSafeTimedSerializer(settings.secret_key)


def hash_password(password: str) -> str:
    return _bcrypt.hashpw(password.encode(), _bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return _bcrypt.checkpw(plain.encode(), hashed.encode())


def create_session_token(username: str) -> str:
    return _serializer.dumps({"user": username})


def verify_session_token(token: str) -> str | None:
    try:
        data = _serializer.loads(token, max_age=settings.session_max_age)
        return data.get("user")
    except (BadSignature, SignatureExpired):
        return None


def get_current_admin(request: Request) -> str:
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user = verify_session_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Session expired")
    return user


def check_credentials(username: str, password: str, db: Session | None = None) -> bool:
    """Check credentials against DB admin users first, then fall back to env-var admin."""
    if db is not None:
        from app.models.models import AdminUser
        user = db.query(AdminUser).filter(AdminUser.email == username).first()
        if user:
            return verify_password(password, user.hashed_password)

    # Fallback: env-var based admin (for backwards compat / first boot)
    return username == settings.admin_username and password == settings.admin_password
