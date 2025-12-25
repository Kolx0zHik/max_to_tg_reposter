import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Settings:
    max_phone: str
    max_token: str
    app_version: str
    work_dir: Path
    state_path: Path
    subscribers_path: Path
    catalog_path: Path
    log_path: Path
    startup_history: int
    log_level: str
    telegram_token: str
    admin_chat_id: int


def load_settings() -> Settings:
    max_token = os.getenv("MAX_TOKEN")
    if not max_token:
        raise ValueError("MAX_TOKEN is required (value from __oneme_auth)")

    max_phone = os.getenv("MAX_PHONE")
    if not max_phone:
        raise ValueError("MAX_PHONE is required for PyMax")

    telegram_token = os.getenv("TG_TOKEN")
    if not telegram_token:
        raise ValueError("TG_TOKEN is required for Telegram bot")

    app_version = os.getenv("MAX_APP_VERSION", "25.12.13")
    work_dir = Path(os.getenv("MAX_WORK_DIR", ".max_session"))
    state_path = Path(os.getenv("STATE_PATH", "data/state.json"))
    startup_history = int(os.getenv("STARTUP_HISTORY", "3"))
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    admin_chat_id = int(os.getenv("ADMIN_CHAT_ID", "0"))
    subscribers_path = Path(os.getenv("SUBSCRIBERS_PATH", "data/subscribers.json"))
    catalog_path = Path(os.getenv("CATALOG_PATH", "data/catalog.json"))
    log_path = Path(os.getenv("LOG_PATH", "data/app.log"))

    return Settings(
        max_phone=max_phone,
        max_token=max_token,
        app_version=app_version,
        work_dir=work_dir,
        state_path=state_path,
        subscribers_path=subscribers_path,
        catalog_path=catalog_path,
        log_path=log_path,
        startup_history=startup_history,
        log_level=log_level,
        telegram_token=telegram_token,
        admin_chat_id=admin_chat_id,
    )
