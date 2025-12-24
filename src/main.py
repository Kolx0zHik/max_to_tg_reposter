import asyncio
import logging
from collections import defaultdict
from typing import Dict, List, Optional

from aiogram import Bot, Dispatcher, F
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message as TgMessage
from aiogram.utils.keyboard import InlineKeyboardBuilder
from pymax import MaxClient
from pymax.payloads import UserAgentPayload
from pymax.types import FileAttach, Message, PhotoAttach, VideoAttach

from app.config import Settings, load_settings
from app.formatter import format_message_text
from app.state_store import StateStore
from app.subscriptions import CatalogStore, SubscriptionsStore
from app.telegram_sender import TelegramSender
from app.utils import fetch_bytes


def build_chat_title_map(client: MaxClient, chat_ids: List[int]) -> Dict[int, str]:
    titles: Dict[int, str] = {}
    for chat in client.chats:
        if chat.id in chat_ids:
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
    routes_map: Dict[int, List[int]],
    subs: SubscriptionsStore,
    chat_titles: Dict[int, str],
    override_chat_id: Optional[int] = None,
) -> None:
    chat_id = override_chat_id or message.chat_id
    if chat_id is None:
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
    tg_chats = set(routes_map.get(chat_id, []))
    tg_chats.update(subs.get_subscribers_for_chat(chat_id))
    if not tg_chats:
        return

    for tg_chat in sorted(tg_chats):
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
    routes_map: Dict[int, List[int]] = defaultdict(list)
    initial_chat_ids: List[int] = []
    for route in settings.routes:
        initial_chat_ids.append(route.max_chat_id)
        if route.tg_chat_id is not None:
            routes_map[route.max_chat_id].append(route.tg_chat_id)
    tg = TelegramSender(settings.telegram_token)
    subs = SubscriptionsStore(settings.subscribers_path)
    catalog = CatalogStore(settings.catalog_path, initial_chat_ids)

    user_agent = UserAgentPayload(device_type="WEB", app_version=settings.app_version)
    client = MaxClient(
        phone=settings.max_phone,
        token=settings.max_token,
        headers=user_agent,
        work_dir=str(settings.work_dir),
        send_fake_telemetry=True,
    )
    # Принудительно кладём актуальный токен в базу PyMax, чтобы не использовать устаревший из session.db
    client._token = settings.max_token  # type: ignore[attr-defined]
    client._database.update_auth_token(client._device_id, settings.max_token)  # type: ignore[attr-defined]

    chat_titles: Dict[int, str] = {}

    bot = Bot(settings.telegram_token)
    dp = Dispatcher()

    def is_admin(user_id: int) -> bool:
        return settings.admin_chat_id and user_id == settings.admin_chat_id

    def group_title(chat_id: int) -> str:
        return chat_titles.get(chat_id, str(chat_id))

    def refresh_chat_title(chat_id: int) -> None:
        for chat in client.chats:
            if chat.id == chat_id:
                chat_titles[chat_id] = chat.title or str(chat_id)
                return

    def build_groups_keyboard(user_id: int) -> InlineKeyboardMarkup:
        builder = InlineKeyboardBuilder()
        user_chats = set(subs.get_user_chats(user_id))
        for cid in catalog.list_visible():
            label = group_title(cid)
            if cid in user_chats:
                builder.button(text=f"✅ {label}", callback_data=f"unsub:{cid}")
            else:
                builder.button(text=f"➕ {label}", callback_data=f"sub:{cid}")
        builder.button(text="Мои подписки", callback_data="my")
        if is_admin(user_id):
            builder.button(text="Админ", callback_data="admin")
        builder.adjust(1)
        return builder.as_markup()

    def build_admin_keyboard() -> InlineKeyboardMarkup:
        builder = InlineKeyboardBuilder()
        builder.button(text="Добавить группу", callback_data="admin_add")
        builder.button(text="Скрыть группу", callback_data="admin_hide")
        builder.button(text="Подписчики", callback_data="admin_users")
        builder.button(text="Рассылка", callback_data="admin_broadcast")
        builder.button(text="Назад", callback_data="back")
        builder.adjust(1)
        return builder.as_markup()

    pending_admin: Dict[int, str] = {}

    @client.on_start
    async def on_start() -> None:
        nonlocal chat_titles
        chat_titles = build_chat_title_map(client, catalog.list_visible())
        client.logger.info("Catalog groups: %s", catalog.list_visible())
        client.logger.info("Active routes: %s", dict(routes_map))
        client.logger.info("Chat titles detected: %s", chat_titles)

        for route in settings.routes:
            history = await client.fetch_history(chat_id=route.max_chat_id, backward=settings.startup_history)
            client.logger.info("Startup history chat=%s count=%s", route.max_chat_id, len(history or []))
            if not history:
                continue
            for msg in sorted(history, key=lambda m: m.id):
                await handle_message(
                    msg,
                    settings,
                    client,
                    tg,
                    state,
                    routes_map,
                    subs,
                    chat_titles,
                    override_chat_id=route.max_chat_id,
                )

    @client.on_message()
    async def on_message(message: Message) -> None:
        await handle_message(message, settings, client, tg, state, routes_map, subs, chat_titles)

    @dp.message(F.text == "/start")
    async def start_cmd(message: TgMessage) -> None:
        subs.ensure_user(message.chat.id, message.from_user.username, message.from_user.full_name)
        await message.answer(
            "Выберите группы MAX для подписки:",
            reply_markup=build_groups_keyboard(message.chat.id),
        )

    @dp.callback_query(F.data == "back")
    async def back_to_menu(cb: CallbackQuery) -> None:
        await cb.message.edit_text(
            "Выберите группы MAX для подписки:",
            reply_markup=build_groups_keyboard(cb.from_user.id),
        )
        await cb.answer()

    @dp.callback_query(F.data == "my")
    async def my_subs(cb: CallbackQuery) -> None:
        chats = subs.get_user_chats(cb.from_user.id)
        if not chats:
            text = "Подписок нет."
        else:
            text = "Ваши подписки:\n" + "\n".join(f"- {group_title(cid)}" for cid in chats)
        await cb.message.edit_text(text, reply_markup=build_groups_keyboard(cb.from_user.id))
        await cb.answer()

    @dp.callback_query(F.data.startswith("sub:"))
    async def subscribe_cb(cb: CallbackQuery) -> None:
        chat_id = int(cb.data.split(":", 1)[1])
        subs.subscribe(cb.from_user.id, chat_id)
        if settings.admin_chat_id:
            await bot.send_message(
                settings.admin_chat_id,
                f"Подписка: {cb.from_user.full_name} ({cb.from_user.id}) → {group_title(chat_id)}",
            )
        await cb.message.edit_reply_markup(reply_markup=build_groups_keyboard(cb.from_user.id))
        await cb.answer("Подписка добавлена")

    @dp.callback_query(F.data.startswith("unsub:"))
    async def unsubscribe_cb(cb: CallbackQuery) -> None:
        chat_id = int(cb.data.split(":", 1)[1])
        subs.unsubscribe(cb.from_user.id, chat_id)
        await cb.message.edit_reply_markup(reply_markup=build_groups_keyboard(cb.from_user.id))
        await cb.answer("Подписка удалена")

    @dp.callback_query(F.data == "admin")
    async def admin_menu(cb: CallbackQuery) -> None:
        if not is_admin(cb.from_user.id):
            await cb.answer("Доступ запрещён", show_alert=True)
            return
        await cb.message.edit_text("Админ-меню:", reply_markup=build_admin_keyboard())
        await cb.answer()

    @dp.callback_query(F.data == "admin_add")
    async def admin_add(cb: CallbackQuery) -> None:
        if not is_admin(cb.from_user.id):
            await cb.answer("Доступ запрещён", show_alert=True)
            return
        pending_admin[cb.from_user.id] = "add"
        await cb.message.edit_text("Отправьте max_chat_id для добавления:", reply_markup=build_admin_keyboard())
        await cb.answer()

    @dp.callback_query(F.data == "admin_hide")
    async def admin_hide(cb: CallbackQuery) -> None:
        if not is_admin(cb.from_user.id):
            await cb.answer("Доступ запрещён", show_alert=True)
            return
        pending_admin[cb.from_user.id] = "hide"
        await cb.message.edit_text("Отправьте max_chat_id для скрытия:", reply_markup=build_admin_keyboard())
        await cb.answer()

    @dp.callback_query(F.data == "admin_users")
    async def admin_users(cb: CallbackQuery) -> None:
        if not is_admin(cb.from_user.id):
            await cb.answer("Доступ запрещён", show_alert=True)
            return
        users = subs.list_users()
        if not users:
            text = "Подписчиков нет."
        else:
            lines = []
            for uid, info in users.items():
                name = info.get("name") or ""
                username = info.get("username")
                label = f"{name} (@{username})" if username else name
                lines.append(f"- {uid} {label}".strip())
            text = "Подписчики:\n" + "\n".join(lines)
        await cb.message.edit_text(text, reply_markup=build_admin_keyboard())
        await cb.answer()

    @dp.callback_query(F.data == "admin_broadcast")
    async def admin_broadcast(cb: CallbackQuery) -> None:
        if not is_admin(cb.from_user.id):
            await cb.answer("Доступ запрещён", show_alert=True)
            return
        pending_admin[cb.from_user.id] = "broadcast"
        await cb.message.edit_text("Отправьте текст рассылки:", reply_markup=build_admin_keyboard())
        await cb.answer()

    @dp.message()
    async def admin_text(message: TgMessage) -> None:
        if not is_admin(message.from_user.id):
            return
        action = pending_admin.pop(message.from_user.id, "")
        if not action:
            return
        if action in ("add", "hide"):
            try:
                chat_id = int(message.text.strip())
            except Exception:
                await message.answer("Нужен числовой max_chat_id.")
                return
            if action == "add":
                catalog.add_group(chat_id)
                refresh_chat_title(chat_id)
                await message.answer(f"Группа добавлена: {group_title(chat_id)}")
            else:
                catalog.hide_group(chat_id)
                await message.answer(f"Группа скрыта: {group_title(chat_id)}")
            return
        if action == "broadcast":
            users = subs.list_users()
            for uid in users.keys():
                await bot.send_message(uid, message.text)
            await message.answer("Рассылка отправлена.")

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        logging.getLogger(__name__).info("Telegram polling started")
        await asyncio.gather(client.start(), dp.start_polling(bot))
    finally:
        await tg.close()


if __name__ == "__main__":
    asyncio.run(run())
