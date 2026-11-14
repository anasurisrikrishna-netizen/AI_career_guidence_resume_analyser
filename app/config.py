import os
from pathlib import Path
from datetime import timedelta

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY")
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL") or (
        f"sqlite:///{PROJECT_ROOT / 'instance' / 'app.sqlite'}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    MAX_CONTENT_LENGTH = int(os.getenv("MAX_UPLOAD_BYTES", str(5 * 1024 * 1024)))
    MAX_RESUME_TEXT_CHARS = int(os.getenv("MAX_RESUME_TEXT_CHARS", "50000"))
    MAX_RESUME_PAGES = int(os.getenv("MAX_RESUME_PAGES", "80"))
    _upload_folder = Path(os.getenv("UPLOAD_FOLDER", str(PROJECT_ROOT / "instance" / "uploads")))
    UPLOAD_FOLDER = str(_upload_folder if _upload_folder.is_absolute() else PROJECT_ROOT / _upload_folder)
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    ADZUNA_APP_ID = os.getenv("ADZUNA_APP_ID")
    ADZUNA_APP_KEY = os.getenv("ADZUNA_APP_KEY")
    ADZUNA_COUNTRY_CODE = os.getenv("ADZUNA_COUNTRY_CODE", "in").lower()
    JOB_SEARCH_TIMEOUT_SECONDS = float(os.getenv("JOB_SEARCH_TIMEOUT_SECONDS", "8"))
    AI_MAX_INPUT_TOKENS = int(os.getenv("AI_MAX_INPUT_TOKENS", "20000"))
    AI_MAX_OUTPUT_TOKENS = int(os.getenv("AI_MAX_OUTPUT_TOKENS", "4096"))
    AI_MAX_DAILY_TOKENS_PER_USER = int(os.getenv("AI_MAX_DAILY_TOKENS_PER_USER", "100000"))
    AI_RETRY_ATTEMPTS = int(os.getenv("AI_RETRY_ATTEMPTS", "3"))
    AI_RETRY_BASE_SECONDS = float(os.getenv("AI_RETRY_BASE_SECONDS", "0.5"))
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "false").lower() == "true"
    SESSION_PROTECTION = "strong"
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)
    WTF_CSRF_TIME_LIMIT = 3600
    RATELIMIT_HEADERS_ENABLED = True
    RATELIMIT_DEFAULT = os.getenv("RATELIMIT_DEFAULT", "200 per day, 50 per hour")
    RATELIMIT_STORAGE_URI = os.getenv("RATELIMIT_STORAGE_URI", "memory://")
