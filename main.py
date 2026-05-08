import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import (
    TelegramForbiddenError,
    TelegramRetryAfter,
    TelegramBadRequest,
)

import handlers
from config import CHECK_INTERVAL, FIRST_RUN_LIMIT, TOKEN
from db import (
    close as db_close,
    count_seen,
    get_active_users,
    increment_sent,
    init_db,
    is_seen,
    mark_seen,
    set_active,
)
from formatter import format_ad
from parser import fetch_ads, matches_filters

log = logging.getLogger("kufar_bot")


async def _send_ad(bot: Bot, chat_id: int, ad: dict) -> bool:
    """True если сообщение реально доставлено пользователю."""
    text = format_ad(ad)
    try:
        await bot.send_message(chat_id, text, disable_web_page_preview=False)
        return True
    except TelegramRetryAfter as e:
        log.warning("[SEND] flood control, sleep %ss", e.retry_after)
        await asyncio.sleep(e.retry_after + 1)
        try:
            await bot.send_message(chat_id, text, disable_web_page_preview=False)
            return True
        except Exception as exc:
            log.exception("[SEND] retry failed for %s: %s", chat_id, exc)
            return False
    except TelegramForbiddenError:
        log.info("[SEND] %s заблокировал бота, выключаю подписку", chat_id)
        set_active(chat_id, False)
        return False
    except TelegramBadRequest as exc:
        log.warning("[SEND] BadRequest для %s: %s", chat_id, exc)
        return False
    except Exception as exc:
        log.exception("[SEND] неизвестная ошибка для %s: %s", chat_id, exc)
        return False


async def _process_user(bot: Bot, user: dict, ads: list[dict]) -> None:
    chat_id = user["chat_id"]
    matched = [a for a in ads if matches_filters(a, user["max_price"], user["keywords"])]
    if not matched:
        return

    is_first_run = count_seen(chat_id) == 0

    if is_first_run:
        # Первый запуск для юзера — кидаем только N самых свежих, остальное молча помечаем seen
        to_send = matched[:FIRST_RUN_LIMIT]
        to_skip = matched[FIRST_RUN_LIMIT:]
        for ad in to_skip:
            mark_seen(chat_id, ad["link"])
    else:
        to_send = matched

    for ad in to_send:
        if is_seen(chat_id, ad["link"]):
            continue
        ok = await _send_ad(bot, chat_id, ad)
        mark_seen(chat_id, ad["link"])
        if ok:
            increment_sent(chat_id)
        await asyncio.sleep(0.05)


async def poller(bot: Bot) -> None:
    """Фоновый цикл: парсит Kufar и рассылает новые объявления подписчикам."""
    while True:
        try:
            users = get_active_users()
            if not users:
                log.info("[POLLER] нет активных подписчиков, жду")
            else:
                log.info("[POLLER] поиск объявлений для %d юзеров", len(users))
                ads = await fetch_ads()
                log.info("[POLLER] получено %d объявлений", len(ads))

                for user in users:
                    try:
                        await _process_user(bot, user, ads)
                    except Exception:
                        log.exception("[POLLER] ошибка обработки юзера %s", user["chat_id"])
        except Exception:
            log.exception("[POLLER] ошибка в цикле")

        await asyncio.sleep(CHECK_INTERVAL)


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stdout,
    )

    if not TOKEN:
        log.error("Не найден TOKEN в .env")
        sys.exit(1)

    init_db()

    bot = Bot(
        token=TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp.include_router(handlers.router)

    poll_task = asyncio.create_task(poller(bot))

    log.info("[BOT] стартую long polling")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        poll_task.cancel()
        try:
            await poll_task
        except asyncio.CancelledError:
            pass
        await bot.session.close()
        db_close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log.info("[BOT] остановлен")
