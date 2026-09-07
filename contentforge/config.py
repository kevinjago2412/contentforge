import os
from pathlib import Path

from dotenv import load_dotenv


def load_config() -> dict:
    """Load configuration from .env file if present."""
    env_path = Path.cwd() / ".env"
    if env_path.exists():
        load_dotenv(env_path)

    return {
        "api_key": os.getenv("OPENAI_API_KEY", ""),
        "base_url": os.getenv("OPENAI_BASE_URL", ""),
        "model": os.getenv("MODEL", "claude-sonnet-5"),
    }
