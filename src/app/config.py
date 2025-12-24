import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import yaml


@dataclass
class Route:
    max_chat_id: int
    tg_chat_id: Optional[int]


@dataclass
class Settings:
    max_phone: str
    max_token: str
    app_version: str
    work_dir: Path
    state_path: Path
    subscribers_path: Path
    catalog_path: Path
    routes: List[Route]
    startup_history: int
    log_level: str
    telegram_token: str
    admin_chat_id: int


def load_routes(config_path: Path) -> List[Route]:
    if not config_path.exists():
        config_path.parent.mkdir(parents=True, exist_ok=True)
        template = {
            "routes": [
                {"max_chat_id": -123456789},
                {"max_chat_id": -987654321},
            ]
        }
        config_path.write_text(
            yaml.safe_dump(template, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        raise FileNotFoundError(
            f"Config file {config_path} was missing. A template was created; please fill it and restart."
        )

    with config_path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    routes_raw = data.get("routes", [])
    routes: List[Route] = []
    for item in routes_raw:
        try:
            routes.append(
                Route(
                    max_chat_id=int(item["max_chat_id"]),
                    tg_chat_id=int(item["tg_chat_id"]) if "tg_chat_id" in item else None,
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
    admin_chat_id = int(os.getenv("ADMIN_CHAT_ID", "0"))
    subscribers_path = Path(os.getenv("SUBSCRIBERS_PATH", "data/subscribers.json"))
    catalog_path = Path(os.getenv("CATALOG_PATH", "data/catalog.json"))

    return Settings(
        max_phone=max_phone,
        max_token=max_token,
        app_version=app_version,
        work_dir=work_dir,
        state_path=state_path,
        subscribers_path=subscribers_path,
        catalog_path=catalog_path,
        routes=routes,
        startup_history=startup_history,
        log_level=log_level,
        telegram_token=telegram_token,
        admin_chat_id=admin_chat_id,
    )
