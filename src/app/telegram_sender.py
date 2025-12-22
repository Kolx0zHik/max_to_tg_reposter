from __future__ import annotations

import asyncio
import logging
from typing import Optional

import httpx


class TelegramSender:
    def __init__(self, token: str, timeout: float = 15.0):
        self.base_url = f"https://api.telegram.org/bot{token}"
        self.client = httpx.AsyncClient(timeout=timeout)
        self.logger = logging.getLogger(__name__)

    async def close(self) -> None:
        await self.client.aclose()

    async def send_text(self, chat_id: int, text: str) -> None:
        await self._post("/sendMessage", {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": False})

    async def send_photo(self, chat_id: int, data: bytes, filename: str = "photo.jpg") -> None:
        files = {"photo": (filename, data)}
        await self._post("/sendPhoto", {"chat_id": chat_id}, files=files)

    async def send_document(self, chat_id: int, data: bytes, filename: str) -> None:
        files = {"document": (filename, data)}
        await self._post("/sendDocument", {"chat_id": chat_id}, files=files)

    async def send_video(self, chat_id: int, data: bytes, filename: str = "video.mp4") -> None:
        files = {"video": (filename, data)}
        await self._post("/sendVideo", {"chat_id": chat_id}, files=files)

    async def _post(self, path: str, payload: dict, files: Optional[dict] = None) -> None:
        url = f"{self.base_url}{path}"
        try:
            resp = await self.client.post(url, data=payload if files else None, json=None if files else payload, files=files)
            resp.raise_for_status()
            data = resp.json()
            if not data.get("ok"):
                self.logger.error("Telegram error: %s", data)
        except Exception:
            self.logger.exception("Telegram request failed path=%s", path)
            await asyncio.sleep(1)
