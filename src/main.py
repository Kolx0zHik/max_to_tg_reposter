import asyncio
import logging
from typing import Dict, Optional

from pymax import MaxClient
from pymax.payloads import UserAgentPayload
from pymax.types import FileAttach, Message, PhotoAttach, VideoAttach

from app.config import Settings, load_settings
from app.formatter import format_message_text
from app.state_store import StateStore
from app.telegram_sender import TelegramSender
from app.utils import fetch_bytes


def build_chat_title_map(client: MaxClient, routes: Dict[int, int]) -> Dict[int, str]:
    titles: Dict[int, str] = {}
    for chat in client.chats:
        if chat.id in routes:
            titles[chat.id] = chat.title or str(chat.id)
    return titles


async def resolve_author(client: MaxClient, sender_id: Optional[int]) -> Optional[str]:
    if not sender_id:
        return None
    try:
        user = await client.get_user(sender_id)
        if user and user.names:
            return str(user.names[0])
    except Exception:
        client.logger.exception("Failed to resolve author user_id=%s", sender_id)
    return None


async def send_attachments(message: Message, client: MaxClient, tg: TelegramSender, chat_id: int) -> None:
    if not message.attaches:
        return

    for attach in message.attaches:
        try:
            if isinstance(attach, PhotoAttach):
                data, name = await fetch_bytes(attach.base_url)
                await tg.send_photo(chat_id, data, filename=name or "photo.jpg")
            elif isinstance(attach, VideoAttach):
                video = await client.get_video_by_id(chat_id=message.chat_id, message_id=message.id, video_id=attach.video_id)
                if video:
                    data, name = await fetch_bytes(video.url)
                    await tg.send_video(chat_id, data, filename=name or "video.mp4")
            elif isinstance(attach, FileAttach):
                file_resp = await client.get_file_by_id(chat_id=message.chat_id, message_id=message.id, file_id=attach.file_id)
                if file_resp:
                    data, name = await fetch_bytes(file_resp.url)
                    await tg.send_document(chat_id, data, filename=name or attach.name or "file")
        except Exception:
            client.logger.exception("Failed to send attachment message_id=%s", message.id)
        await asyncio.sleep(0.5)


async def handle_message(
    message: Message,
    settings: Settings,
    client: MaxClient,
    tg: TelegramSender,
    state: StateStore,
    routes_map: Dict[int, int],
    chat_titles: Dict[int, str],
    override_chat_id: Optional[int] = None,
) -> None:
    chat_id = override_chat_id or message.chat_id
    if chat_id is None or chat_id not in routes_map:
        return

    try:
        msg_id = int(message.id)
    except Exception:
        client.logger.error("Invalid message id type: %r", message.id)
        return

    last_id = state.get_last(chat_id)
    if msg_id <= last_id:
        return

    author = await resolve_author(client, message.sender)
    chat_title = chat_titles.get(chat_id, str(chat_id))
    text = format_message_text(message, chat_title, author)
    tg_chat = routes_map[chat_id]

    await tg.send_text(tg_chat, text)
    await send_attachments(message, client, tg, tg_chat)

    state.set_last(chat_id, msg_id)


async def run() -> None:
    settings = load_settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    state = StateStore(settings.state_path)
    routes_map = {route.max_chat_id: route.tg_chat_id for route in settings.routes}
    tg = TelegramSender(settings.telegram_token)

    user_agent = UserAgentPayload(device_type="WEB", app_version=settings.app_version)
    client = MaxClient(
        phone=settings.max_phone,
        token=settings.max_token,
        headers=user_agent,
        work_dir=str(settings.work_dir),
        send_fake_telemetry=True,
    )

    chat_titles: Dict[int, str] = {}

    @client.on_start
    async def on_start() -> None:
        nonlocal chat_titles
        chat_titles = build_chat_title_map(client, routes_map)
        client.logger.info("Active routes: %s", routes_map)
        client.logger.info("Chat titles detected: %s", chat_titles)

        for route in settings.routes:
            history = await client.fetch_history(chat_id=route.max_chat_id, backward=settings.startup_history)
            client.logger.info("Startup history chat=%s count=%s", route.max_chat_id, len(history or []))
            if not history:
                continue
            for msg in sorted(history, key=lambda m: m.id):
                await handle_message(msg, settings, client, tg, state, routes_map, chat_titles, override_chat_id=route.max_chat_id)

    @client.on_message()
    async def on_message(message: Message) -> None:
        await handle_message(message, settings, client, tg, state, routes_map, chat_titles)

    try:
        await client.start()
    finally:
        await tg.close()


if __name__ == "__main__":
    asyncio.run(run())
