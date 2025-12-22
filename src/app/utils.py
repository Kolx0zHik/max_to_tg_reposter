import logging

import httpx


async def fetch_bytes(url: str, headers: dict | None = None) -> tuple[bytes, str]:
    """
    Загружает файл по URL и возвращает байты и предполагаемое имя.
    """
    async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
        resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        filename = resp.headers.get("X-File-Name") or url.split("/")[-1] or "file"
        return resp.content, filename
