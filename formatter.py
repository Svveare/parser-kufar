from html import escape


def _esc(value) -> str:
    if value is None:
        return ""
    return escape(str(value))


def format_ad(ad: dict) -> str:
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

    return (
        f"<b>Статус подписки:</b> {active}\n"
        f"<b>Макс. цена:</b> {max_price} р.\n"
        f"<b>Ключевики:</b> {_esc(kw)}\n"
        f"<b>Прислано объявлений:</b> {sent}"
    )


HELP_TEXT = (
    "<b>Kufar Support Bot</b>\n\n"
    "Слежу за свежими объявлениями на Kufar и кидаю подходящие тебе сразу как появятся.\n\n"
    "<b>Команды:</b>\n"
    "/start — подписаться на рассылку\n"
    "/stop — отписаться\n"
    "/status — текущие настройки и статистика\n"
    "/setprice 600 — поменять макс. цену\n"
    "/setkeywords iphone 11, iphone 12 — поменять ключевики (через запятую)\n"
    "/help — это сообщение"
)
