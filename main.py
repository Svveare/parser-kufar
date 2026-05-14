import asyncio
import logging
import signal
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import (
    TelegramForbiddenError,
    TelegramRetryAfter,
    TelegramBadRequest,
)
from aiogram.types import InputMediaPhoto

import handlers
from config import (
    CHECK_INTERVAL,
    DB_PATH,
    FIRST_RUN_LIMIT,
    MARKET_DISCOUNT_THRESHOLD,
    REGULAR_CHECK_INTERVAL,
    SQLITE_SYNCHRONOUS,
    TOKEN,
    VIP_CHECK_INTERVAL,
)
from db import (
    SQLITE_PATH,
    avg_market_price,
    close as db_close,
    count_seen,
    get_active_users,
    increment_sent,
    init_db,
    is_seen,
    mark_seen,
    save_market_price,
    set_active,
)
from formatter import format_ad
from filters import ad_device_key, is_exchange_ad, matches_filters
from kufar_fetch import fetch_ads

log = logging.getLogger("kufar_bot")

# Для VIP-режимов «все айфоны» — не ограничиваем ценой из профиля
_VIP_SPECIAL_MAX_PRICE = 99_999_999
last_run_at: dict[int, float] = {}


def _ingest_market_prices_from_ads(ads: list[dict]) -> None:
    """Пополняет market_prices из текущего батча листинга (один ответ API — одна база для средней)."""
    for a in ads:
        if not matches_filters(a, _VIP_SPECIAL_MAX_PRICE, [], smart_filtering=True):
            continue
        dk = ad_device_key(a)
        price = a.get("price")
        link = a.get("link")
        if not dk or not isinstance(price, int) or price <= 0:
            continue
        if not isinstance(link, str) or not link.strip():
            continue
        save_market_price(link, dk, price)


async def _send_ad(
    bot: Bot,
    chat_id: int,
    ad: dict,
    *,
    market_avg_price: int | None = None,
    below_market: bool = False,
) -> bool:
    """True если сообщение реально доставлено пользователю."""
    text = format_ad(ad, market_avg_price=market_avg_price, below_market=below_market)
    photos = [p for p in (ad.get("photo_urls") or []) if isinstance(p, str) and p.strip()]

    async def _deliver() -> None:
        if photos:
            media = [
                InputMediaPhoto(
                    media=photo,
                    caption=text if i == 0 else None,
                    parse_mode=ParseMode.HTML if i == 0 else None,
                )
                for i, photo in enumerate(photos[:5])
            ]
            await bot.send_media_group(chat_id=chat_id, media=media)
            return
        await bot.send_message(chat_id, text, disable_web_page_preview=False)

    try:
        await _deliver()
        return True
    except TelegramRetryAfter as e:
        log.warning("[SEND] flood control, sleep %ss", e.retry_after)
        await asyncio.sleep(e.retry_after + 1)
        try:
            await _deliver()
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
    is_vip = user.get("role") == "vip"
    feed_mode = (user.get("vip_feed_mode") or "normal") if is_vip else "normal"

    if is_vip and feed_mode == "below_market":
        pool = [
            a
            for a in ads
            if matches_filters(
                a,
                _VIP_SPECIAL_MAX_PRICE,
                [],
                smart_filtering=True,
            )
        ]
        matched = []
        for a in pool:
            dk = ad_device_key(a)
            price = a.get("price")
            if not dk or not isinstance(price, int) or price <= 0:
                continue
            mavg = avg_market_price(dk)
            if mavg and price < int(mavg * MARKET_DISCOUNT_THRESHOLD):
                matched.append(a)
    elif is_vip and feed_mode == "exchange":
        matched = [
            a
            for a in ads
            if matches_filters(
                a,
                _VIP_SPECIAL_MAX_PRICE,
                [],
                smart_filtering=True,
            )
            and is_exchange_ad(a)
        ]
    else:
        matched = [
            a
            for a in ads
            if matches_filters(
                a,
                user["max_price"],
                user["keywords"],
                smart_filtering=is_vip,
            )
        ]
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
        market_avg = None
        below_market = False
        device_key = ad_device_key(ad)
        price = ad.get("price")
        if is_vip:
            if device_key:
                market_avg = avg_market_price(device_key)
            if feed_mode == "below_market":
                below_market = True
            elif market_avg and price and price < int(market_avg * MARKET_DISCOUNT_THRESHOLD):
                below_market = True
        ok = await _send_ad(
            bot,
            chat_id,
            ad,
            market_avg_price=market_avg if is_vip else None,
            below_market=below_market,
        )
        mark_seen(chat_id, ad["link"])
        if ok:
            increment_sent(chat_id)
            if (
                device_key
                and isinstance(price, int)
                and price > 0
            ):
                save_market_price(ad["link"], device_key, price)
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
                _ingest_market_prices_from_ads(ads)

                for user in users:
                    try:
                        if not _should_process_user(user):
                            continue
                        await _process_user(bot, user, ads)
                        last_run_at[user["chat_id"]] = asyncio.get_running_loop().time()
                    except Exception:
                        log.exception("[POLLER] ошибка обработки юзера %s", user["chat_id"])
        except Exception:
            log.exception("[POLLER] ошибка в цикле")

        await asyncio.sleep(CHECK_INTERVAL)


def _should_process_user(user: dict) -> bool:
    chat_id = user["chat_id"]
    now = asyncio.get_running_loop().time()
    prev = last_run_at.get(chat_id)
    if prev is None:
        return True
    interval = VIP_CHECK_INTERVAL if user.get("role") == "vip" else REGULAR_CHECK_INTERVAL
    return (now - prev) >= interval


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
    log.info("[BOT] SQLite synchronous=%s (см. SQLITE_SYNCHRONOUS в .env)", SQLITE_SYNCHRONOUS)
    log.info("[BOT] файл БД: %s (DB_PATH в .env: %s)", SQLITE_PATH, DB_PATH or "не задан")

    bot = Bot(
        token=TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp.include_router(handlers.router)

    def _schedule_stop_polling() -> None:
        asyncio.create_task(dp.stop_polling())

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _schedule_stop_polling)
        except NotImplementedError:
            pass

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
