import asyncio
import logging
from collections import defaultdict
from typing import Dict, List, Optional

from aiogram import Bot, Dispatcher, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message as TgMessage
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


async def send_attachments(
    message: Message,
    client: MaxClient,
    tg: TelegramSender,
    chat_id: int,
    download_headers: Optional[dict] = None,
) -> None:
    if not message.attaches:
        return

    for attach in message.attaches:
        try:
            if isinstance(attach, PhotoAttach):
                data, name = await fetch_bytes(attach.base_url, headers=download_headers)
                await tg.send_photo(chat_id, data, filename=name or "photo.jpg")
            elif isinstance(attach, VideoAttach):
                video = await client.get_video_by_id(chat_id=message.chat_id, message_id=message.id, video_id=attach.video_id)
                if video:
                    data, name = await fetch_bytes(video.url, headers=download_headers)
                    await tg.send_video(chat_id, data, filename=name or "video.mp4")
            elif isinstance(attach, FileAttach):
                file_resp = await client.get_file_by_id(chat_id=message.chat_id, message_id=message.id, file_id=attach.file_id)
                if file_resp:
                    data, name = await fetch_bytes(file_resp.url, headers=download_headers)
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
        download_headers = {"Cookie": f"__oneme_auth={settings.max_token}"}
        await send_attachments(message, client, tg, tg_chat, download_headers=download_headers)

    state.set_last(chat_id, msg_id)


async def run() -> None:
    settings = load_settings()
    settings.log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(settings.log_path, encoding="utf-8"),
        ],
    )

    state = StateStore(settings.state_path)
    routes_map: Dict[int, List[int]] = defaultdict(list)
    initial_chat_ids: List[int] = []
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
        builder.button(text="⬅️ Назад", callback_data="menu")
        builder.adjust(1)
        return builder.as_markup()

    def build_start_keyboard(user_id: int) -> InlineKeyboardMarkup:
        builder = InlineKeyboardBuilder()
        builder.button(text="📚 Выбрать группы", callback_data="groups")
        builder.button(text="🏠 Меню", callback_data="menu")
        if is_admin(user_id):
            builder.button(text="🛠 Админ", callback_data="admin")
        builder.adjust(1)
        return builder.as_markup()

    def build_admin_keyboard() -> InlineKeyboardMarkup:
        builder = InlineKeyboardBuilder()
        builder.button(text="➕ Добавить группу", callback_data="admin_add")
        builder.button(text="🗑 Удалить группу", callback_data="admin_delete")
        builder.button(text="📋 Список групп", callback_data="admin_list")
        builder.button(text="👥 Подписчики", callback_data="admin_users")
        builder.button(text="📄 Логи (50 строк)", callback_data="admin_logs")
        builder.button(text="🏠 Меню", callback_data="menu")
        builder.adjust(1)
        return builder.as_markup()

    def build_delete_keyboard() -> InlineKeyboardMarkup:
        builder = InlineKeyboardBuilder()
        groups = catalog.list_all()
        if not groups:
            builder.button(text="🏠 Меню", callback_data="menu")
            builder.adjust(1)
            return builder.as_markup()
        for g in groups:
            cid = int(g["id"])
            label = f"{group_title(cid)} ({cid})"
            builder.button(text=f"🗑 {label}", callback_data=f"del:{cid}")
        builder.button(text="🏠 Меню", callback_data="menu")
        builder.adjust(1)
        return builder.as_markup()

    def tail_log_lines(max_lines: int = 50) -> str:
        try:
            lines = settings.log_path.read_text(encoding="utf-8").splitlines()
        except Exception:
            return "Лог пуст или недоступен."
        if not lines:
            return "Лог пуст."
        return "\n".join(lines[-max_lines:])

    @client.on_start
    async def on_start() -> None:
        nonlocal chat_titles
        chat_titles = build_chat_title_map(client, catalog.list_visible())
        client.logger.info("Catalog groups: %s", catalog.list_visible())
        client.logger.info("Active routes: %s", dict(routes_map))
        client.logger.info("Chat titles detected: %s", chat_titles)

        for chat_id in catalog.list_visible():
            history = await client.fetch_history(chat_id=chat_id, backward=settings.startup_history)
            client.logger.info("Startup history chat=%s count=%s", chat_id, len(history or []))
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
                    override_chat_id=chat_id,
                )

    @client.on_message()
    async def on_message(message: Message) -> None:
        await handle_message(message, settings, client, tg, state, routes_map, subs, chat_titles)

    @dp.message(F.text == "/start")
    async def start_cmd(message: TgMessage) -> None:
        subs.ensure_user(message.chat.id, message.from_user.username, message.from_user.full_name)
        await message.answer(
            "Привет! Это меню подписок на MAX-группы. 👋\n\n"
            "Нажмите «📚 Выбрать группы», чтобы подписаться.",
            reply_markup=build_start_keyboard(message.chat.id),
        )

    @dp.message(F.text == "/menu")
    async def menu_cmd(message: TgMessage) -> None:
        subs.ensure_user(message.chat.id, message.from_user.username, message.from_user.full_name)
        await message.answer(
            "Привет! Это меню подписок на MAX-группы. 👋\n\n"
            "Нажмите «📚 Выбрать группы», чтобы подписаться.",
            reply_markup=build_start_keyboard(message.chat.id),
        )

    @dp.callback_query(F.data == "menu")
    async def back_to_menu(cb: CallbackQuery) -> None:
        try:
            await cb.message.edit_text(
                "Привет! Это меню подписок на MAX-группы. 👋\n\n"
                "Нажмите «📚 Выбрать группы», чтобы подписаться.",
                reply_markup=build_start_keyboard(cb.from_user.id),
            )
        except Exception:
            pass
        await cb.answer()

    @dp.callback_query(F.data == "groups")
    async def groups_menu(cb: CallbackQuery) -> None:
        await cb.message.edit_text(
            "Выберите группы MAX для подписки: ✨",
            reply_markup=build_groups_keyboard(cb.from_user.id),
        )
        await cb.answer()

    @dp.callback_query(F.data.startswith("sub:"))
    async def subscribe_cb(cb: CallbackQuery) -> None:
        chat_id = int(cb.data.split(":", 1)[1])
        already = chat_id in set(subs.get_user_chats(cb.from_user.id))
        if not already:
            subs.subscribe(cb.from_user.id, chat_id)
            if settings.admin_chat_id:
                await bot.send_message(
                    settings.admin_chat_id,
                    f"Подписка: {cb.from_user.full_name} ({cb.from_user.id}) → {group_title(chat_id)}",
                )
            await cb.answer("✅ Подписка оформлена")
        else:
            await cb.answer("ℹ️ Уже подписаны")
        await cb.message.edit_reply_markup(reply_markup=build_groups_keyboard(cb.from_user.id))

    @dp.callback_query(F.data.startswith("unsub:"))
    async def unsubscribe_cb(cb: CallbackQuery) -> None:
        chat_id = int(cb.data.split(":", 1)[1])
        subs.unsubscribe(cb.from_user.id, chat_id)
        await cb.message.edit_reply_markup(reply_markup=build_groups_keyboard(cb.from_user.id))
        await cb.answer("❌ Подписка удалена")

    pending_admin: Dict[int, str] = {}

    @dp.callback_query(F.data == "admin")
    async def admin_menu(cb: CallbackQuery) -> None:
        if not is_admin(cb.from_user.id):
            await cb.answer("Доступ запрещён", show_alert=True)
            return
        await cb.message.edit_text("Админ-панель:", reply_markup=build_admin_keyboard())
        await cb.answer()

    @dp.callback_query(F.data == "admin_add")
    async def admin_add(cb: CallbackQuery) -> None:
        if not is_admin(cb.from_user.id):
            await cb.answer("Доступ запрещён", show_alert=True)
            return
        pending_admin[cb.from_user.id] = "add"
        await cb.message.edit_text("Отправьте max_chat_id для добавления:", reply_markup=build_admin_keyboard())
        await cb.answer()

    @dp.callback_query(F.data == "admin_delete")
    async def admin_delete(cb: CallbackQuery) -> None:
        if not is_admin(cb.from_user.id):
            await cb.answer("Доступ запрещён", show_alert=True)
            return
        await cb.message.edit_text("Выберите группу для удаления:", reply_markup=build_delete_keyboard())
        await cb.answer()

    @dp.callback_query(F.data == "admin_list")
    async def admin_list(cb: CallbackQuery) -> None:
        if not is_admin(cb.from_user.id):
            await cb.answer("Доступ запрещён", show_alert=True)
            return
        groups = catalog.list_all()
        if not groups:
            text = "Список групп пуст."
        else:
            lines = []
            for g in groups:
                cid = int(g["id"])
                label = f"{group_title(cid)} ({cid})"
                lines.append(f"- {label}")
            text = "Группы:\n" + "\n".join(lines)
        await cb.message.edit_text(text, reply_markup=build_admin_keyboard())
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

    @dp.callback_query(F.data == "admin_logs")
    async def admin_logs(cb: CallbackQuery) -> None:
        if not is_admin(cb.from_user.id):
            await cb.answer("Доступ запрещён", show_alert=True)
            return
        text = tail_log_lines(50)
        await cb.message.edit_text(f"Последние 50 строк:\n\n{text}", reply_markup=build_admin_keyboard())
        await cb.answer()

    @dp.callback_query(F.data.startswith("del:"))
    async def admin_del_chat(cb: CallbackQuery) -> None:
        if not is_admin(cb.from_user.id):
            await cb.answer("Доступ запрещён", show_alert=True)
            return
        chat_id = int(cb.data.split(":", 1)[1])
        catalog.remove_group(chat_id)
        subs.remove_group_from_all(chat_id)
        await cb.message.edit_text("Группа удалена.", reply_markup=build_admin_keyboard())
        await cb.answer()

    @dp.message()
    async def admin_text(message: TgMessage) -> None:
        if not is_admin(message.from_user.id):
            return
        action = pending_admin.pop(message.from_user.id, "")
        if not action:
            return
        if action == "add":
            try:
                chat_id = int(message.text.strip())
            except Exception:
                await message.answer("Нужен числовой max_chat_id.")
                return
            catalog.add_group(chat_id)
            refresh_chat_title(chat_id)
            await message.answer(
                f"Группа добавлена: {group_title(chat_id)} ({chat_id})",
                reply_markup=build_admin_keyboard(),
            )
            return

    @dp.message()
    async def fallback(message: TgMessage) -> None:
        if message.text.startswith("/"):
            await message.answer(
                "Команда не распознана. Нажмите «🏠 Меню».",
                reply_markup=build_start_keyboard(message.chat.id),
            )

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        logging.getLogger(__name__).info("Telegram polling started")
        await asyncio.gather(client.start(), dp.start_polling(bot))
    finally:
        await tg.close()


if __name__ == "__main__":
    asyncio.run(run())
