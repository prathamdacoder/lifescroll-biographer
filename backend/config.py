"""Central configuration. Every secret is read from the environment."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

# ---------------------------------------------------------------- AI (Groq)
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
GROQ_BASE_URL = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1").rstrip("/")
GROQ_MODEL = os.getenv("GROQ_MODEL", "qwen/qwen3.6-27b")

# Tried in order if GROQ_MODEL is decommissioned or unavailable on your account.
GROQ_FALLBACK_MODELS = [
    m.strip() for m in os.getenv(
        "GROQ_FALLBACK_MODELS",
        "qwen/qwen3.6-27b,openai/gpt-oss-120b,llama-3.3-70b-versatile,llama-3.1-8b-instant",
    ).split(",") if m.strip()
]

# Qwen3.6 and gpt-oss are reasoning models; "none"/"low" keeps prose fast and clean.
GROQ_REASONING_EFFORT = os.getenv("GROQ_REASONING_EFFORT", "none").strip().lower()

# ---------------------------------------------------------------- Supabase
SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY", "").strip()
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()

# ---------------------------------------------------------------- Images
# Pollinations needs no API key; set IMAGE_PROVIDER=openai + OPENAI_API_KEY for DALL-E.
IMAGE_PROVIDER = os.getenv("IMAGE_PROVIDER", "pollinations").lower()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()

# ---------------------------------------------------------------- App
SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-insecure-secret-change-me")
DATA_DIR = Path(os.getenv("DATA_DIR", ROOT / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
SQLITE_PATH = DATA_DIR / "lifescroll.db"

# Book shape: 12 chapters x ~2,100 words ~= 50 printed pages.
TARGET_CHAPTERS = int(os.getenv("TARGET_CHAPTERS", "12"))
WORDS_PER_CHAPTER = int(os.getenv("WORDS_PER_CHAPTER", "2100"))
IMAGES_PER_CHAPTER = int(os.getenv("IMAGES_PER_CHAPTER", "6"))  # 5-10 supported

# Updated at runtime by groq_client when a fallback model takes over.
ACTIVE_MODEL = GROQ_MODEL

USE_SUPABASE = bool(SUPABASE_URL and SUPABASE_ANON_KEY)
HAS_GROQ = bool(GROQ_API_KEY)


def public_config() -> dict:
    """Non-secret flags the browser is allowed to know about."""
    return {
        "auth_provider": "supabase" if USE_SUPABASE else "local",
        "supabase_url": SUPABASE_URL if USE_SUPABASE else "",
        "google_oauth": USE_SUPABASE,
        "ai_live": HAS_GROQ,
        "model": ACTIVE_MODEL if HAS_GROQ else "demo-writer",
        "target_chapters": TARGET_CHAPTERS,
        "images_per_chapter": IMAGES_PER_CHAPTER,
    }
