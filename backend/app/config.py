from functools import lru_cache
import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel


load_dotenv()

_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseModel):
    groq_api_key: str | None = None
    groq_model: str = "llama-3.3-70b-versatile"
    cors_origin: str = "http://localhost:5173"
    request_timeout_s: float = 30.0
    nominatim_user_agent: str = "travel-agent/0.1"
    db_path: str = str(_ROOT / "travel_agent.db")


@lru_cache
def get_settings() -> Settings:
    return Settings(
        groq_api_key=os.getenv("GROQ_API_KEY") or None,
        groq_model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
        cors_origin=os.getenv("CORS_ORIGIN", "http://localhost:5173"),
        nominatim_user_agent=os.getenv("NOMINATIM_USER_AGENT", "travel-agent/0.1"),
        db_path=os.getenv("DB_PATH", str(_ROOT / "travel_agent.db")),
    )
