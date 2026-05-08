import logging

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from db import (
    add_user,
    get_user,
    set_active,
    update_keywords,
    update_max_price,
)
from formatter import HELP_TEXT, format_status

log = logging.getLogger(__name__)
router = Router()


@router.message(CommandStart())
async def on_start(msg: Message) -> None:
    chat_id = msg.chat.id
    is_new = add_user(chat_id)
    log.info("[START] chat_id=%s new=%s", chat_id, is_new)

    if is_new:
        await msg.answer(
            "Привет! Подписка активна ✅\n\n"
            "Я буду присылать новые объявления с Kufar по твоим фильтрам.\n"
            "Жми /help чтобы посмотреть команды и настройки."
        )
    else:
        await msg.answer(
            "С возвращением! Подписка снова активна ✅\n"
            "Жми /status чтобы посмотреть текущие настройки."
        )


@router.message(Command("stop"))
async def on_stop(msg: Message) -> None:
    set_active(msg.chat.id, False)
    log.info("[STOP] chat_id=%s", msg.chat.id)
    await msg.answer("Подписка выключена ❌\nЧтобы вернуться — /start")


@router.message(Command("help"))
async def on_help(msg: Message) -> None:
    await msg.answer(HELP_TEXT, disable_web_page_preview=True)


@router.message(Command("status"))
async def on_status(msg: Message) -> None:
    user = get_user(msg.chat.id)
    if user is None:
        await msg.answer("Ты ещё не подписан. Жми /start.")
        return
    await msg.answer(format_status(user))


@router.message(Command("setprice"))
async def on_setprice(msg: Message) -> None:
    if get_user(msg.chat.id) is None:
        await msg.answer("Сначала /start.")
        return

    parts = (msg.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip().isdigit():
        await msg.answer("Используй: <code>/setprice 600</code>")
        return

    price = int(parts[1].strip())
    if price <= 0 or price > 10_000_000:
        await msg.answer("Цена должна быть от 1 до 10 000 000.")
        return

    update_max_price(msg.chat.id, price)
    await msg.answer(f"Ок, теперь макс. цена — <b>{price} р.</b>")


@router.message(Command("setkeywords"))
async def on_setkeywords(msg: Message) -> None:
    if get_user(msg.chat.id) is None:
        await msg.answer("Сначала /start.")
        return

    parts = (msg.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await msg.answer(
            "Используй: <code>/setkeywords iphone 11, iphone 12 mini</code>"
        )
        return

    raw = parts[1]
    keywords = [k.strip() for k in raw.split(",") if k.strip()]
    if not keywords:
        await msg.answer("Не нашёл ни одного ключевика.")
        return
    if len(keywords) > 30:
        await msg.answer("Слишком много ключевиков, максимум 30.")
        return

    update_keywords(msg.chat.id, keywords)
    await msg.answer(
        "Ок, новые ключевики:\n<code>" + ", ".join(keywords) + "</code>"
    )
