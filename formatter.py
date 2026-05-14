from html import escape
from datetime import datetime, timezone

from config import VIP_PRICE_USD


def _esc(value) -> str:
    if value is None:
        return ""
    return escape(str(value))


def format_ad(
    ad: dict, *, market_avg_price: int | None = None, below_market: bool = False
) -> str:
    """Превращает словарь объявления в HTML-сообщение для Telegram."""
    title = _esc(ad.get("title") or "Без названия")

    price = ad.get("price")
    price_usd = ad.get("price_usd")
    if price is not None:
        price_str = f"{price:,}".replace(",", " ") + " р."
        if price_usd:
            price_str += f" (≈ {price_usd}$)"
    else:
        price_str = "цена не указана"

    location = _esc(ad.get("location") or "")
    description = _esc(ad.get("description") or "")
    link = ad.get("link") or ""

    parts = [
        f"📱 <b>{title}</b>",
        f"💰 <b>{_esc(price_str)}</b>",
    ]
    if below_market:
        parts.insert(0, "🔥 <b>НИЖЕ РЫНОЧНОЙ ЦЕНЫ</b>")
    if market_avg_price is not None:
        parts.append(f"📊 Средняя рыночная цена: <b>{market_avg_price} р.</b>")
    if location:
        parts.append(f"📍 <i>{location}</i>")
    if description:
        parts.append("")
        parts.append(description)
    parts.append("")
    parts.append(f'🔗 <a href="{_esc(link)}">Открыть на Kufar</a>')

    return "\n".join(parts)


def format_status(user: dict) -> str:
    active = "включена ✅" if user.get("active") else "выключена ❌"
    keywords = user.get("keywords") or []
    kw = ", ".join(keywords) if keywords else "—"
    max_price = user.get("max_price") or 0
    sent = user.get("sent_count", 0)
    role = "VIP ⭐" if user.get("role") == "vip" else "Обычный"
    vip_until = int(user.get("vip_until") or 0)
    vip_until_text = "—"
    if vip_until > 0:
        dt = datetime.fromtimestamp(vip_until, tz=timezone.utc).astimezone()
        vip_until_text = dt.strftime("%d.%m.%Y %H:%M")

    vip_feed = ""
    if user.get("role") == "vip":
        mode = user.get("vip_feed_mode") or "normal"
        if mode == "below_market":
            vip_feed = "\n<b>VIP-поток:</b> только ниже рынка (все iPhone)"
        elif mode == "exchange":
            vip_feed = "\n<b>VIP-поток:</b> только обмен (все iPhone)"

    paused = ""
    if not user.get("active"):
        paused = (
            "\n\n⚠️ <b>Объявления сейчас не приходят</b> (рассылка выключена).\n"
            "В главном меню нажми <b>«Включить рассылку»</b> или отправь <code>/start</code>."
        )

    return (
        f"<b>Статус подписки:</b> {active}\n"
        f"<b>Тип пользователя:</b> {role}\n"
        f"<b>VIP до:</b> {vip_until_text}\n"
        f"<b>Макс. цена:</b> {max_price} р.\n"
        f"<b>Ключевики:</b> {_esc(kw)}\n"
        f"<b>Прислано объявлений:</b> {sent}"
        f"{vip_feed}"
        f"{paused}"
    )


HELP_TEXT = (
    "<b>Kufar Support Bot</b>\n\n"
    "Присылаю подходящие объявления с Kufar.\n\n"
    "<b>Кратко</b>\n"
    "• <code>/start</code> — меню\n"
    "• <b>Товары</b> и макс. цена — подбор объявлений\n"
    "• VIP — расширение и бета-потоки (см. раздел VIP)\n"
    "• Отписка — в меню; вернуть рассылку — <b>«Включить рассылку»</b> или снова <code>/start</code>\n\n"
    f"VIP: <b>{VIP_PRICE_USD}$</b> / 30 дней (инструкция в разделе «VIP»)."
)
