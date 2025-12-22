import os
from dataclasses import dataclass
from pathlib import Path
from typing import List

import yaml


@dataclass
class Route:
    max_chat_id: int
    tg_chat_id: int


@dataclass
class Settings:
    max_phone: str
    max_token: str
    app_version: str
    work_dir: Path
    state_path: Path
    routes: List[Route]
    startup_history: int
    log_level: str
    telegram_token: str


def load_routes(config_path: Path) -> List[Route]:
    with config_path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    routes_raw = data.get("routes", [])
    routes: List[Route] = []
    for item in routes_raw:
        try:
            routes.append(
                Route(
                    max_chat_id=int(item["max_chat_id"]),
                    tg_chat_id=int(item["tg_chat_id"]),
                )
            )
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"Invalid route entry: {item}") from exc
    if not routes:
        raise ValueError("No routes configured in config file")
    return routes


def load_settings() -> Settings:
    config_path = Path(os.getenv("CONFIG_PATH", "config/groups.yaml"))
    routes = load_routes(config_path)

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

    return Settings(
        max_phone=max_phone,
        max_token=max_token,
        app_version=app_version,
        work_dir=work_dir,
        state_path=state_path,
        routes=routes,
        startup_history=startup_history,
        log_level=log_level,
        telegram_token=telegram_token,
    )
