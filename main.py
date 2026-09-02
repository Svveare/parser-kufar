import asyncio
import logging
import signal
import sys
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

import bot_ui
import handlers
from config import (
    ADMIN_IDS,
    AVITO_DEV_MOCK,
    AVITO_ENABLED,
    AVITO_FEED_FILE,
    AVITO_FEED_URL,
    AVITO_LIVE_ENABLED,
    AVITO_SEARCH_URL,
    CHECK_INTERVAL,
    MARKET_DISCOUNT_THRESHOLD,
    PUBLIC_BASE_URL,
    REGULAR_CHECK_INTERVAL,
    ROLLYPAY_CALLBACK_URL,
    ROLLYPAY_ENABLED,
    SQLITE_SYNCHRONOUS,
    TOKEN,
    VIP_CHECK_INTERVAL,
)
from db import (
    SQLITE_PATH,
    close as db_close,
    create_promo_code,
    get_user,
    init_db,
    set_vip,
)
from logging_setup import configure_logging
from payments.webhook_server import start_webhook_server, vip_payment_poll_loop
from poller import poller

log = logging.getLogger("kufar_bot")

# Owner chat: grant VIP after deploy when Bothost panel is unavailable
_OWNER_CHAT_ID = 7938175227
_OWNER_PROMO = "SVVEARE90"
_OWNER_VIP_DAYS = 90


def _bootstrap_owner_vip() -> None:
    """Seed promo + grant 90d VIP to owner if not already long-active."""
    import time

    created = create_promo_code(_OWNER_PROMO, vip_days=_OWNER_VIP_DAYS, max_uses=5)
    if created:
        log.info("owner promo seeded code=%s days=%s", _OWNER_PROMO, _OWNER_VIP_DAYS)

    user = get_user(_OWNER_CHAT_ID)
    if user is None:
        log.warning("owner chat_id=%s not in db yet — open bot once, then redeploy", _OWNER_CHAT_ID)
        return
    now = int(time.time())
    vip_until = int(user.get("vip_until") or 0)
    if user.get("role") == "vip" and vip_until > now + 60 * 24 * 3600:
        log.info("owner already has VIP until=%s — skip auto-grant", vip_until)
        return
    set_vip(_OWNER_CHAT_ID, days=_OWNER_VIP_DAYS)
    log.info("owner VIP granted chat_id=%s days=%s", _OWNER_CHAT_ID, _OWNER_VIP_DAYS)


async def main() -> None:
    configure_logging()

    if not TOKEN:
        log.error("TOKEN missing in .env")
        sys.exit(1)
    if not ADMIN_IDS:
        log.warning("ADMIN_IDS empty — admin panel unavailable")
    if CHECK_INTERVAL < 1:
        log.error("CHECK_INTERVAL must be >= 1")
        sys.exit(1)
    if not 0 < MARKET_DISCOUNT_THRESHOLD < 1:
        log.error("MARKET_DISCOUNT_THRESHOLD must be between 0 and 1")
        sys.exit(1)

    init_db()
    _bootstrap_owner_vip()

    from kufar_geo import resolve_geo_path

    geo_path = resolve_geo_path()
    if geo_path is None:
        log.warning(
            "kufar_geo.json not found — city text search uses shortcuts only; "
            "expected geo/kufar_geo.json in project root"
        )
    else:
        log.info("geo map path=%s", geo_path)

    bot = Bot(
        token=TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    me = await bot.get_me()
    bot_ui.BOT_USERNAME = (me.username or "").strip()
    if not bot_ui.BOT_USERNAME:
        log.warning("bot has no @username — referral links disabled")

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

    if AVITO_ENABLED and AVITO_DEV_MOCK:
        log.warning(
            "AVITO_DEV_MOCK=true — Avito poll uses geo/avito_mock_ads.json, not live data"
        )
    elif AVITO_ENABLED and AVITO_SEARCH_URL:
        log.info("avito external search url=%s", AVITO_SEARCH_URL)
    elif AVITO_ENABLED and AVITO_FEED_URL:
        log.info("avito feed configured url=%s", AVITO_FEED_URL)
    elif AVITO_ENABLED and AVITO_LIVE_ENABLED:
        log.info("avito live fetch enabled (built-in web API)")
    elif AVITO_ENABLED and AVITO_FEED_FILE:
        log.info("avito feed file=%s", AVITO_FEED_FILE)
    elif AVITO_ENABLED:
        log.warning(
            "AVITO_ENABLED but no data channel — set AVITO_LIVE_ENABLED or external URL"
        )

    poll_task = asyncio.create_task(poller(bot))
    webhook_runner = await start_webhook_server(bot)
    vip_poll_task = asyncio.create_task(vip_payment_poll_loop(bot))

    if ROLLYPAY_ENABLED:
        log.info(
            "rollypay enabled callback=%s public_base=%s",
            ROLLYPAY_CALLBACK_URL or "(set PUBLIC_BASE_URL / DOMAIN)",
            PUBLIC_BASE_URL or "(unset)",
        )

    log.info(
        "ready @%s db=%s poll=%ss vip_poll=%ss regular_poll=%ss sqlite_sync=%s",
        bot_ui.BOT_USERNAME or "?",
        SQLITE_PATH,
        CHECK_INTERVAL,
        VIP_CHECK_INTERVAL,
        REGULAR_CHECK_INTERVAL,
        SQLITE_SYNCHRONOUS,
    )
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        poll_task.cancel()
        vip_poll_task.cancel()
        try:
            await poll_task
        except asyncio.CancelledError:
            pass
        try:
            await vip_poll_task
        except asyncio.CancelledError:
            pass
        if webhook_runner is not None:
            await webhook_runner.cleanup()
        await bot.session.close()
        db_close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log.info("shutdown")
