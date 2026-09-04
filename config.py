import os


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY") or "local-development-only-change-me"
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "sqlite:///pigmyflow_dev.db").replace(
        "postgres://", "postgresql://", 1
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "false").lower() == "true"
    APP_TIMEZONE = os.getenv("APP_TIMEZONE", "Asia/Kolkata")
    WTF_CSRF_ENABLED = False
    MAX_CONTENT_LENGTH = int(os.getenv("MAX_UPLOAD_BYTES", 2 * 1024 * 1024))
    UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER", os.path.join(os.path.dirname(__file__), "static", "uploads"))
