import logging
import secrets
import string
from html import escape

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from config import ADMIN_IDS, DEVICE_CATALOG, MAX_PRICE_PRESETS, VIP_PRICE_USD
from goods_tree import (
    APPLE_LINES,
    GOODS_PER_PAGE,
    LINE_BASIC,
    LINE_LABELS,
    LINE_MAX,
    LINE_PRO,
    SAMSUNG_LINE_LABELS,
    SAMSUNG_SERIES_FLIP,
    SAMSUNG_SERIES_FOLD,
    SAMSUNG_LINES,
    SAMSUNG_SERIES_LABELS,
    SAMSUNG_SERIES_LINES,
    SAMSUNG_SERIES_S,
)
from db import (
    add_user,
    clear_market_prices,
    count_users_active,
    count_users_total,
    count_users_vip,
    create_promo_code,
    get_user,
    list_active_promo_codes,
    list_users_page,
    redeem_promo_code,
    revoke_vip,
    set_active,
    set_vip,
    update_keywords,
    update_max_price,
    update_user_username,
    update_vip_feed_mode,
)
from formatter import HELP_TEXT, format_status

log = logging.getLogger(__name__)
router = Router()
PER_PAGE = 8
ADM_USERS_PER_PAGE = 6


class PromoCodeState(StatesGroup):
    waiting_code = State()


class CustomPriceState(StatesGroup):
    waiting_price = State()


class AdminPromoState(StatesGroup):
    waiting_random = State()
    waiting_manual = State()


def _maybe_refresh_username(chat_id: int, from_user) -> None:
    if from_user is None or from_user.id != chat_id:
        return
    update_user_username(chat_id, from_user.username)


async def enrich_username_from_get_chat(bot: Bot, user: dict) -> None:
    """Если в БД нет @username — пробуем get_chat (работает для пользователей, с кем бот общался)."""
    if (user.get("username") or "").strip():
        return
    chat_id = user.get("chat_id")
    if chat_id is None:
        return
    try:
        chat = await bot.get_chat(chat_id)
    except (TelegramBadRequest, TelegramForbiddenError):
        return
    un = getattr(chat, "username", None) or ""
    un = un.strip()
    if not un:
        return
    user["username"] = un
    update_user_username(int(chat_id), un)


async def format_user_status_html(bot: Bot, user: dict) -> str:
    await enrich_username_from_get_chat(bot, user)
    return format_status(user)

_GOODS_CRUMB = "📦 <b>Товары</b>"


def _max_keyword_slots(user: dict) -> int:
    return 9999 if user.get("role") == "vip" else 5


def _is_vip_user(user: dict | None) -> bool:
    return bool(user and user.get("role") == "vip")


def _flatten_groups(groups: dict[str, tuple[str, ...]]) -> list[str]:
    items: list[str] = []
    for values in groups.values():
        items.extend(values)
    return items


def _apple_models() -> list[str]:
    return _flatten_groups(APPLE_LINES)


def _samsung_models() -> list[str]:
    return _flatten_groups(SAMSUNG_LINES)


def _models_for_scope(scope: str) -> list[str]:
    if scope == "a":
        return _apple_models()
    if scope == "s":
        return _samsung_models()
    return list(DEVICE_CATALOG)


def _model_list_title(scope: str) -> str:
    if scope == "a":
        return "Apple › <b>Все модели</b>"
    if scope == "s":
        return "Samsung › <b>Все модели</b>"
    return "<b>Все модели</b>"


def _model_list_bulk_callback(scope: str) -> str:
    if scope == "a":
        return "bulk:apple"
    if scope == "s":
        return "bulk:samsung"
    return "bulk:all"


def _model_list_back_button(scope: str) -> InlineKeyboardButton:
    if scope == "a":
        return InlineKeyboardButton(text="⬅️ К линейкам", callback_data="goods:a")
    if scope == "s":
        return InlineKeyboardButton(text="⬅️ К сериям", callback_data="goods:s")
    return InlineKeyboardButton(text="⬅️ К брендам", callback_data="goods:m")


def _samsung_series_models(series_slug: str) -> list[str]:
    items: list[str] = []
    for line_slug in SAMSUNG_SERIES_LINES.get(series_slug, ()):
        items.extend(SAMSUNG_LINES.get(line_slug, ()))
    return items


def _samsung_series_for_line(line_slug: str) -> str:
    for series_slug, line_slugs in SAMSUNG_SERIES_LINES.items():
        if line_slug in line_slugs:
            return series_slug
    return SAMSUNG_SERIES_S


def _samsung_line_back_button(line_slug: str) -> InlineKeyboardButton:
    series_slug = _samsung_series_for_line(line_slug)
    if series_slug in (SAMSUNG_SERIES_FLIP, SAMSUNG_SERIES_FOLD):
        return InlineKeyboardButton(text="⬅️ К сериям", callback_data="goods:s")
    return InlineKeyboardButton(text="⬅️ К линейкам", callback_data=f"sg:{series_slug}")


def _select_models(user: dict, models: list[str] | tuple[str, ...]) -> list[str]:
    selected = [k.strip().lower() for k in (user.get("keywords") or []) if k.strip()]
    seen = set(selected)
    for model in models:
        value = model.strip().lower()
        if value and value not in seen:
            selected.append(value)
            seen.add(value)
    return selected


def _toggle_models(user: dict, models: list[str] | tuple[str, ...]) -> tuple[list[str], bool]:
    selected = [k.strip().lower() for k in (user.get("keywords") or []) if k.strip()]
    selected_set = set(selected)
    model_values = [m.strip().lower() for m in models if m.strip()]
    model_set = set(model_values)
    if model_set and model_set.issubset(selected_set):
        return [k for k in selected if k not in model_set], False
    return _select_models(user, model_values), True


def _goods_category_text() -> str:
    return (
        f"{_GOODS_CRUMB}\n\n"
        "Выберите <b>категорию</b>.\n\n"
        "<i>Сейчас доступны мобильные устройства; остальное — в разработке.</i>"
    )


def _goods_category_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📱 Мобильные устройства", callback_data="goods:m")],
            [
                InlineKeyboardButton(text="💻 Ноутбуки (скоро)", callback_data="goods:soon:lap"),
                InlineKeyboardButton(text="📦 Другое (скоро)", callback_data="goods:soon:oth"),
            ],
            [InlineKeyboardButton(text="⬅️ В меню", callback_data="nav:home")],
        ]
    )


def _goods_mobile_brands_text() -> str:
    return (
        f"{_GOODS_CRUMB} › <b>Мобильные</b>\n\n"
        "Выберите <b>производителя</b>."
    )


def _goods_mobile_brands_keyboard(user: dict | None = None) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text="Apple", callback_data="goods:a"),
            InlineKeyboardButton(text="Samsung", callback_data="goods:s"),
        ],
    ]
    if _is_vip_user(user):
        rows.append([InlineKeyboardButton(text="📋 Выбрать все модели", callback_data="bulk:all")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="goods:h")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _goods_samsung_text() -> str:
    return (
        f"{_GOODS_CRUMB} › <b>Мобильные</b> › <b>Samsung</b>\n\n"
        "Выберите <b>серию</b>, затем линейку и модели."
    )


def _goods_apple_lines_text() -> str:
    return (
        f"{_GOODS_CRUMB} › <b>Мобильные</b> › <b>Apple</b>\n\n"
        "Выберите <b>линейку</b>, затем отметьте модели."
    )


def _goods_apple_lines_keyboard(user: dict | None = None) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text=f"🍎 {LINE_LABELS[LINE_BASIC]}", callback_data=f"gt:{LINE_BASIC}:p:0"),
            InlineKeyboardButton(text=f"🍎 {LINE_LABELS[LINE_PRO]}", callback_data=f"gt:{LINE_PRO}:p:0"),
        ],
        [
            InlineKeyboardButton(text=f"🍎 {LINE_LABELS[LINE_MAX]}", callback_data=f"gt:{LINE_MAX}:p:0"),
        ],
    ]
    if _is_vip_user(user):
        rows.append([InlineKeyboardButton(text="📋 Выбрать все iPhone", callback_data="bulk:apple")])
    rows.extend(
        [
            [InlineKeyboardButton(text="📋 Все модели списком", callback_data="goods:w")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="goods:m")],
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _goods_samsung_keyboard(user: dict | None = None) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="Samsung Galaxy S", callback_data=f"sg:{SAMSUNG_SERIES_S}")],
        [
            InlineKeyboardButton(text="Samsung Z Flip", callback_data=f"st:{SAMSUNG_SERIES_FLIP}:p:0"),
            InlineKeyboardButton(text="Samsung Z Fold", callback_data=f"st:{SAMSUNG_SERIES_FOLD}:p:0"),
        ],
    ]
    if _is_vip_user(user):
        rows.append([InlineKeyboardButton(text="📋 Выбрать все Samsung", callback_data="bulk:samsung")])
    rows.extend(
        [
            [InlineKeyboardButton(text="📋 Все модели списком", callback_data="goods:sw")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="goods:m")],
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _samsung_series_text(series_slug: str) -> str:
    title = SAMSUNG_SERIES_LABELS.get(series_slug, "Samsung")
    return (
        f"{_GOODS_CRUMB} › <b>Мобильные</b> › <b>Samsung</b> › <b>{title}</b>\n\n"
        "Выберите <b>линейку</b>."
    )


def _samsung_series_keyboard(series_slug: str, user: dict | None = None) -> InlineKeyboardMarkup | None:
    line_slugs = SAMSUNG_SERIES_LINES.get(series_slug)
    if not line_slugs:
        return None
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for line_slug in line_slugs:
        label = SAMSUNG_LINE_LABELS.get(line_slug, line_slug)
        if not SAMSUNG_LINES.get(line_slug):
            continue
        row.append(InlineKeyboardButton(text=label, callback_data=f"st:{line_slug}:p:0"))
        if len(row) >= 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    if _is_vip_user(user):
        rows.append([InlineKeyboardButton(text="📋 Выбрать всю серию", callback_data=f"bulk:ss:{series_slug}")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="goods:s")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _samsung_line_pick_text(line_slug: str) -> str:
    title = SAMSUNG_LINE_LABELS.get(line_slug, line_slug)
    return (
        f"{_GOODS_CRUMB} › <b>Мобильные</b> › <b>Samsung</b> › <b>{title}</b>\n\n"
        "Нажмите на модель — <b>вкл/выкл</b>.\n"
        f"Лимит ручного выбора для обычного пользователя: до {_max_keyword_slots({'role': 'regular'})} позиций.\n"
        "Ниже — <b>Готово</b>, возврат к линейкам или в меню."
    )


def _samsung_line_keyboard(user: dict, line_slug: str, page: int) -> InlineKeyboardMarkup | None:
    models = SAMSUNG_LINES.get(line_slug)
    if not models:
        return None
    total_pages = max(1, (len(models) + GOODS_PER_PAGE - 1) // GOODS_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    start = page * GOODS_PER_PAGE
    chunk = models[start : start + GOODS_PER_PAGE]
    selected = {k.strip().lower() for k in (user.get("keywords") or []) if k.strip()}

    rows: list[list[InlineKeyboardButton]] = []
    for i in range(0, len(chunk), 2):
        row: list[InlineKeyboardButton] = []
        for j in range(2):
            if i + j >= len(chunk):
                continue
            global_idx = start + i + j
            item = chunk[i + j]
            mark = "✅ " if item.lower() in selected else ""
            row.append(
                InlineKeyboardButton(
                    text=f"{mark}{item}",
                    callback_data=f"st:{line_slug}:t:{global_idx}",
                )
            )
        if row:
            rows.append(row)

    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"st:{line_slug}:p:{page - 1}"))
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data=f"st:{line_slug}:x:0"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"st:{line_slug}:p:{page + 1}"))
    rows.append(nav)
    if _is_vip_user(user):
        rows.append(
            [
                InlineKeyboardButton(text="📋 Выбрать всю линейку", callback_data=f"bulk:sg:{line_slug}"),
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(text="Готово ✅", callback_data="kw:done"),
            _samsung_line_back_button(line_slug),
        ]
    )
    rows.append([InlineKeyboardButton(text="🏠 В меню", callback_data="nav:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _goods_line_pick_text(line_slug: str) -> str:
    title = LINE_LABELS.get(line_slug, line_slug)
    return (
        f"{_GOODS_CRUMB} › <b>Мобильные</b> › <b>Apple</b> › <b>{title}</b>\n\n"
        "Нажмите на модель — <b>вкл/выкл</b>.\n"
        f"Лимит ручного выбора для обычного пользователя: до {_max_keyword_slots({'role': 'regular'})} позиций.\n"
        "Ниже — <b>Готово</b>, возврат к линейкам или в меню."
    )


def _goods_line_keyboard(user: dict, line_slug: str, page: int) -> InlineKeyboardMarkup | None:
    models = APPLE_LINES.get(line_slug)
    if not models:
        return None
    total_pages = max(1, (len(models) + GOODS_PER_PAGE - 1) // GOODS_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    start = page * GOODS_PER_PAGE
    chunk = models[start : start + GOODS_PER_PAGE]
    selected = {k.strip().lower() for k in (user.get("keywords") or []) if k.strip()}

    rows: list[list[InlineKeyboardButton]] = []
    for i in range(0, len(chunk), 2):
        row: list[InlineKeyboardButton] = []
        for j in range(2):
            if i + j >= len(chunk):
                continue
            global_idx = start + i + j
            item = chunk[i + j]
            mark = "✅ " if item.lower() in selected else ""
            row.append(
                InlineKeyboardButton(
                    text=f"{mark}{item}",
                    callback_data=f"gt:{line_slug}:t:{global_idx}",
                )
            )
        if row:
            rows.append(row)

    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"gt:{line_slug}:p:{page - 1}"))
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data=f"gt:{line_slug}:x:0"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"gt:{line_slug}:p:{page + 1}"))
    rows.append(nav)
    if _is_vip_user(user):
        rows.append(
            [
                InlineKeyboardButton(text="📋 Выбрать всю линейку", callback_data=f"bulk:ap:{line_slug}"),
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(text="Готово ✅", callback_data="kw:done"),
            InlineKeyboardButton(text="⬅️ К линейкам", callback_data="goods:a"),
        ]
    )
    rows.append([InlineKeyboardButton(text="🏠 В меню", callback_data="nav:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def _actor_user_id(msg: Message) -> int:
    if msg.from_user:
        return msg.from_user.id
    return msg.chat.id


async def _safe_edit_message(
    cb: CallbackQuery,
    text: str,
    *,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    if cb.message is None:
        return
    try:
        await cb.message.edit_text(
            text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML,
        )
    except TelegramBadRequest as e:
        err = str(e).lower()
        if "message is not modified" in err or "not modified" in err:
            return
        log.warning("[EDIT] TelegramBadRequest: %s", e)
    except Exception as e:
        log.exception("[EDIT] failed: %s", e)


def _admin_home_text() -> str:
    return (
        "🔐 <b>Админ-панель</b>\n\n"
        "Управление ботом — только через кнопки ниже.\n"
        "Отдельные админ-команды не нужны: всё здесь.\n"
        "<i>Пользователи работают с ботом через /start и кнопки меню.</i>\n\n"
        "<i>Подсказка:</i> пользователи в списке — от новых к старым."
    )


def _admin_main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📊 Статистика", callback_data="adm:st"),
                InlineKeyboardButton(text="👥 Пользователи", callback_data="adm:us:0"),
            ],
            [
                InlineKeyboardButton(
                    text="🧹 Сбросить глобальные цены рынка",
                    callback_data="adm:mp",
                ),
            ],
            [InlineKeyboardButton(text="🎟 Добавить промокод", callback_data="adm:promo")],
            [InlineKeyboardButton(text="🔄 Обновить панель", callback_data="adm:h")],
            [InlineKeyboardButton(text="👤 К меню бота", callback_data="nav:home")],
        ]
    )


def _admin_stats_text() -> str:
    total = count_users_total()
    active = count_users_active()
    vips = count_users_vip()
    return (
        "📊 <b>Статистика</b>\n\n"
        f"Всего пользователей в базе: <b>{total}</b>\n"
        f"С активной подпиской: <b>{active}</b>\n"
        f"С действующим VIP: <b>{vips}</b>"
    )


def _admin_stats_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ В главное меню", callback_data="adm:h")],
        ]
    )


def _admin_users_page_text(page: int) -> str:
    total = count_users_total()
    if total == 0:
        return "👥 <b>Пользователи</b>\n\nПока никого нет в базе."
    pages = max(1, (total + ADM_USERS_PER_PAGE - 1) // ADM_USERS_PER_PAGE)
    page = max(0, min(page, pages - 1))
    return (
        "👥 <b>Пользователи</b>\n\n"
        f"Страница <b>{page + 1}</b> из <b>{pages}</b> · всего <b>{total}</b>\n"
        "Нажми на пользователя, чтобы открыть карточку."
    )


def _admin_users_keyboard(page: int) -> InlineKeyboardMarkup:
    total = count_users_total()
    rows: list[list[InlineKeyboardButton]] = []
    if total == 0:
        rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="adm:h")])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    pages = max(1, (total + ADM_USERS_PER_PAGE - 1) // ADM_USERS_PER_PAGE)
    page = max(0, min(page, pages - 1))
    offset = page * ADM_USERS_PER_PAGE
    chunk = list_users_page(offset=offset, limit=ADM_USERS_PER_PAGE)

    for u in chunk:
        cid = u["chat_id"]
        role_icon = "⭐" if u.get("role") == "vip" else "·"
        act = "✅" if u.get("active") else "⏸"
        n_kw = len(u.get("keywords") or [])
        un = (u.get("username") or "").strip()
        suffix = f" · {n_kw} устр."
        prefix = f"{act}{role_icon} "
        if un:
            room = 58 - len(prefix) - len(suffix)
            if room >= 4:
                handle = f"@{un}" if len(un) + 1 <= room else f"@{un[: max(1, room - 2)]}…"
            else:
                handle = str(cid)
        else:
            handle = str(cid)
        label = prefix + handle + suffix
        if len(label) > 58:
            label = f"{prefix}{cid}"
        rows.append([InlineKeyboardButton(text=label, callback_data=f"adm:u:{cid}")])

    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"adm:us:{page - 1}"))
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{pages}", callback_data="adm:x"))
    if page < pages - 1:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"adm:us:{page + 1}"))
    rows.append(nav)
    rows.append([InlineKeyboardButton(text="⬅️ В главное меню", callback_data="adm:h")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _admin_user_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="VIP 7 дн.", callback_data=f"adm:vip:{chat_id}:7"),
                InlineKeyboardButton(text="VIP 30 дн.", callback_data=f"adm:vip:{chat_id}:30"),
            ],
            [
                InlineKeyboardButton(text="VIP 14 дн.", callback_data=f"adm:vip:{chat_id}:14"),
                InlineKeyboardButton(text="Снять VIP", callback_data=f"adm:unv:{chat_id}"),
            ],
            [
                InlineKeyboardButton(text="⬅️ К списку", callback_data="adm:us:0"),
                InlineKeyboardButton(text="🏠 В меню", callback_data="adm:h"),
            ],
        ]
    )


def _admin_market_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Да, очистить", callback_data="adm:mp:go"),
                InlineKeyboardButton(text="Отмена", callback_data="adm:h"),
            ],
        ]
    )


def _admin_promos_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📋 Посмотреть существующие промокоды", callback_data="adm:promo:list")],
            [
                InlineKeyboardButton(text="🎲 Добавить случайно", callback_data="adm:promo:random"),
                InlineKeyboardButton(text="✍️ Добавить вручную", callback_data="adm:promo:manual"),
            ],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="adm:h")],
        ]
    )


def _admin_promos_text() -> str:
    return (
        "🎟 <b>Промокоды</b>\n\n"
        "Выберите действие ниже."
    )


def _promo_codes_list_text() -> str:
    promos = list_active_promo_codes()
    if not promos:
        return "🎟 <b>Промокоды</b>\n\nАктуальных промокодов нет."
    lines = ["🎟 <b>Актуальные промокоды</b>", ""]
    for p in promos:
        max_uses = int(p.get("max_uses") or 0)
        uses = int(p.get("uses") or 0)
        limit = "без лимита" if max_uses <= 0 else f"{uses}/{max_uses}"
        lines.append(
            f"<code>{escape(str(p.get('code') or ''))}</code> — VIP {int(p.get('vip_days') or 0)} дн. · активации: {limit}"
        )
    return "\n".join(lines)


def _generate_promo_code() -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(16))


def _main_home_text(user: dict | None, *, is_new: bool) -> str:
    if user is None:
        return "Нажми <code>/start</code>, чтобы зарегистрироваться."
    intro = "Привет!" if is_new else "С возвращением!"
    sub = "включена ✅" if user.get("active") else "выключена ❌"
    lines = [
        intro,
        "",
        f"Рассылка Kufar: <b>{sub}</b>",
    ]
    if not user.get("active"):
        lines += [
            "",
            "Объявления <b>не приходят</b>. Включи снова кнопкой <b>«Включить рассылку»</b> ниже "
            "или командой <code>/start</code>.",
        ]
    if user.get("role") == "vip":
        mode = user.get("vip_feed_mode") or "normal"
        if mode == "below_market":
            lines += [
                "",
                "🔥 <b>VIP-поток:</b> только объявления ниже средней цены по рынку (все смартфоны из каталога). "
                "Повторное нажатие кнопки — выключить.",
            ]
        elif mode == "exchange":
            lines += [
                "",
                "🔄 <b>VIP-поток:</b> только объявления про обмен (все смартфоны из каталога). "
                "Повторное нажатие кнопки — выключить.",
            ]
        else:
            lines += [
                "",
                "⭐ <b>VIP:</b> дополнительно можно включить потоки «ниже рынка» или «только обмен» "
                "(все смартфоны из каталога, не только выбранные модели) — кнопками ниже.",
            ]
    lines += ["", "Навигация — <b>кнопками</b>. Пропало меню — <code>/start</code>."]
    return "\n".join(lines)


def _main_menu_keyboard(*, is_admin: bool, user: dict | None = None) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if user and user.get("active"):
        rows.append([InlineKeyboardButton(text="⛔ Отписаться", callback_data="nav:stop")])
    if user and not user.get("active"):
        rows.append(
            [InlineKeyboardButton(text="🔔 Включить рассылку", callback_data="nav:resume")],
        )
    rows.extend(
        [
            [
                InlineKeyboardButton(text="📊 Статус", callback_data="nav:status"),
                InlineKeyboardButton(text="📦 Товары", callback_data="nav:goods"),
            ],
            [
                InlineKeyboardButton(text="💰 Макс. цена", callback_data="nav:price"),
                InlineKeyboardButton(text="⭐ VIP", callback_data="nav:vip"),
            ],
        ]
    )
    if user and user.get("role") == "vip":
        mode = user.get("vip_feed_mode") or "normal"
        t_bm = "🔥 Ниже рынка (бета)"
        if mode == "below_market":
            t_bm = "🔥 Ниже рынка (бета) ✓"
        t_ex = "🔄 Обмен"
        if mode == "exchange":
            t_ex = "🔄 Обмен ✓"
        rows.append(
            [
                InlineKeyboardButton(text=t_bm, callback_data="nav:vipf:bm"),
                InlineKeyboardButton(text=t_ex, callback_data="nav:vipf:ex"),
            ]
        )
    bottom = [
        InlineKeyboardButton(text="❓ Помощь", callback_data="nav:help"),
        InlineKeyboardButton(text="🎟 Промокоды", callback_data="nav:promo"),
    ]
    rows.append(bottom)
    if is_admin:
        rows.append([InlineKeyboardButton(text="🔐 Админ-панель", callback_data="nav:admin")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _nav_back_home_button() -> list[InlineKeyboardButton]:
    return [InlineKeyboardButton(text="⬅️ В меню", callback_data="nav:home")]


def _promo_back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="назад", callback_data="nav:home")],
        ]
    )


def _price_presets_keyboard(user: dict | None) -> InlineKeyboardMarkup:
    cur = user.get("max_price") if user else None
    row: list[InlineKeyboardButton] = []
    rows: list[list[InlineKeyboardButton]] = []
    for p in MAX_PRICE_PRESETS:
        label = f"✓ {p} р." if cur is not None and int(cur) == int(p) else f"{p} р."
        row.append(InlineKeyboardButton(text=label, callback_data=f"nav:set:{p}"))
        if len(row) >= 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    if _is_vip_user(user):
        rows.append([InlineKeyboardButton(text="🎯 Своя цена", callback_data="nav:price:custom")])
    rows.append(_nav_back_home_button())
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _price_screen_text(user: dict | None) -> str:
    cur = user.get("max_price") if user else None
    cur_txt = f"<b>{cur}</b> р." if cur is not None else "—"
    return (
        "💰 <b>Максимальная цена</b>\n\n"
        f"Сейчас: {cur_txt}\n\n"
        "Выбери лимит кнопкой ниже."
    )


def _status_reply_markup(user: dict) -> InlineKeyboardMarkup:
    row = list(_nav_back_home_button())
    if not user.get("active"):
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🔔 Включить рассылку", callback_data="nav:resume")],
                row,
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=[row])


def _stop_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Да, отписаться", callback_data="nav:stop:yes"),
                InlineKeyboardButton(text="Отмена", callback_data="nav:home"),
            ],
        ]
    )


def _vip_info_text() -> str:
    return (
        "⭐ <b>VIP</b>\n\n"
        f"Подписка: <b>{VIP_PRICE_USD}$</b> на 30 дней.\n"
        "По оплате напишите: @manohio\n"
        "После оплаты админ активирует VIP вручную.\n\n"
        "С VIP доступны бета-потоки: <b>ниже рынка</b> и <b>только обмен</b> "
        "(все смартфоны из каталога, не только выбранные модели) — кнопками в главном меню."
    )


@router.message(CommandStart())
async def on_start(msg: Message, state: FSMContext) -> None:
    chat_id = msg.chat.id
    await state.clear()
    un = msg.from_user.username if msg.from_user else None
    is_new = add_user(chat_id, username=un)
    log.info("[START] chat_id=%s new=%s", chat_id, is_new)
    user = get_user(chat_id)
    uid = _actor_user_id(msg)
    await msg.answer(
        _main_home_text(user, is_new=is_new),
        reply_markup=_main_menu_keyboard(is_admin=_is_admin(uid), user=user),
        parse_mode=ParseMode.HTML,
    )


@router.message(Command("admin"))
async def on_admin(msg: Message, state: FSMContext) -> None:
    await state.clear()
    uid = _actor_user_id(msg)
    if not _is_admin(uid):
        await msg.answer(
            "<b>Нет доступа.</b>",
            parse_mode=ParseMode.HTML,
        )
        return
    await msg.answer(
        _admin_home_text(),
        reply_markup=_admin_main_keyboard(),
        parse_mode=ParseMode.HTML,
    )


@router.callback_query(lambda c: (c.data or "").startswith("nav:"))
async def on_nav_callback(cb: CallbackQuery, state: FSMContext) -> None:
    if cb.message is None:
        await cb.answer()
        return
    chat_id = cb.message.chat.id
    uid = cb.from_user.id if cb.from_user else 0
    data = (cb.data or "").strip()
    parts = data.split(":")

    user = get_user(chat_id)
    _maybe_refresh_username(chat_id, cb.from_user)
    if user is not None:
        user = get_user(chat_id)
    is_admin = _is_admin(uid)

    try:
        if data == "nav:home":
            await state.clear()
            if user is None:
                await _safe_edit_message(
                    cb,
                    "Сначала нажми <code>/start</code>.",
                    reply_markup=None,
                )
                await cb.answer()
                return
            await _safe_edit_message(
                cb,
                _main_home_text(user, is_new=False),
                reply_markup=_main_menu_keyboard(is_admin=is_admin, user=user),
            )
            await cb.answer()
            return

        if user is None:
            await cb.answer("Сначала /start", show_alert=True)
            return

        if data == "nav:resume":
            if user.get("active"):
                await cb.answer("Рассылка уже включена")
                return
            set_active(chat_id, True)
            log.info("[RESUME] chat_id=%s", chat_id)
            user = get_user(chat_id)
            if user is None:
                await cb.answer("Ошибка", show_alert=True)
                return
            await _safe_edit_message(
                cb,
                _main_home_text(user, is_new=False),
                reply_markup=_main_menu_keyboard(is_admin=is_admin, user=user),
            )
            await cb.answer("Рассылка включена")
            return

        if data in ("nav:vipf:bm", "nav:vipf:ex"):
            if user.get("role") != "vip":
                await cb.answer("Только для VIP", show_alert=True)
                return
            cur = user.get("vip_feed_mode") or "normal"
            if data == "nav:vipf:bm":
                new_mode = "normal" if cur == "below_market" else "below_market"
            else:
                new_mode = "normal" if cur == "exchange" else "exchange"
            update_vip_feed_mode(chat_id, new_mode)
            user = get_user(chat_id)
            if user is None:
                await cb.answer("Ошибка", show_alert=True)
                return
            await _safe_edit_message(
                cb,
                _main_home_text(user, is_new=False),
                reply_markup=_main_menu_keyboard(is_admin=is_admin, user=user),
            )
            hint = (
                "Только ниже рынка (все смартфоны из каталога)"
                if new_mode == "below_market"
                else ("Только обмен (все смартфоны из каталога)" if new_mode == "exchange" else "Обычная рассылка")
            )
            await cb.answer(hint)
            return

        if data == "nav:status":
            status_html = await format_user_status_html(cb.bot, user)
            await _safe_edit_message(
                cb,
                status_html,
                reply_markup=_status_reply_markup(user),
            )
            await cb.answer()
            return

        if data in ("nav:goods", "nav:devices"):
            await _safe_edit_message(
                cb,
                _goods_category_text(),
                reply_markup=_goods_category_keyboard(),
            )
            await cb.answer()
            return

        if data == "nav:price":
            await state.clear()
            await _safe_edit_message(
                cb,
                _price_screen_text(user),
                reply_markup=_price_presets_keyboard(user),
            )
            await cb.answer()
            return

        if data == "nav:price:custom":
            if not _is_vip_user(user):
                await cb.answer("Только для VIP", show_alert=True)
                return
            await state.set_state(CustomPriceState.waiting_price)
            await _safe_edit_message(
                cb,
                "🎯 <b>Своя максимальная цена</b>\n\nВведите максимальную цену в рублях одним числом.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[_nav_back_home_button()]),
            )
            await cb.answer()
            return

        if len(parts) == 3 and parts[0] == "nav" and parts[1] == "set" and parts[2].isdigit():
            price = int(parts[2])
            if 1 <= price <= 10_000_000:
                update_max_price(chat_id, price)
            user = get_user(chat_id)
            await _safe_edit_message(
                cb,
                _price_screen_text(user),
                reply_markup=_price_presets_keyboard(user),
            )
            await cb.answer("Сохранено")
            return

        if data == "nav:promo":
            await state.set_state(PromoCodeState.waiting_code)
            await _safe_edit_message(
                cb,
                "🎟️ Введите промокод:",
                reply_markup=_promo_back_keyboard(),
            )
            await cb.answer()
            return

        if data == "nav:vip":
            await _safe_edit_message(
                cb,
                _vip_info_text(),
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[_nav_back_home_button()]),
            )
            await cb.answer()
            return

        if data == "nav:help":
            await _safe_edit_message(
                cb,
                HELP_TEXT,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[_nav_back_home_button()]),
            )
            await cb.answer()
            return

        if data == "nav:stop:yes":
            set_active(chat_id, False)
            log.info("[STOP] chat_id=%s (inline)", chat_id)
            user = get_user(chat_id)
            await _safe_edit_message(
                cb,
                "Подписка выключена ❌\n\n"
                "Чтобы снова получать объявления — кнопка <b>«Включить рассылку»</b> в главном меню "
                "или команда <code>/start</code>.",
                reply_markup=_main_menu_keyboard(is_admin=is_admin, user=user)
                if user
                else InlineKeyboardMarkup(inline_keyboard=[_nav_back_home_button()]),
            )
            await cb.answer("Готово")
            return

        if data == "nav:stop":
            await _safe_edit_message(
                cb,
                "⛔ <b>Отписаться от рассылки?</b>\n\n"
                "Объявления перестанут приходить.\n"
                "Включить снова: кнопка <b>«Включить рассылку»</b> в меню или <code>/start</code>.",
                reply_markup=_stop_confirm_keyboard(),
            )
            await cb.answer()
            return

        if data == "nav:admin":
            if not is_admin:
                await cb.answer("Нет доступа", show_alert=True)
                return
            await state.clear()
            await _safe_edit_message(
                cb,
                _admin_home_text(),
                reply_markup=_admin_main_keyboard(),
            )
            await cb.answer()
            return

        await cb.answer("Неизвестное действие", show_alert=True)
    except Exception:
        log.exception("[NAV] error data=%s", data)
        try:
            await cb.answer("Ошибка", show_alert=True)
        except Exception:
            pass


@router.callback_query(lambda c: (c.data or "").startswith("bulk:"))
async def on_bulk_select_callback(cb: CallbackQuery) -> None:
    if cb.message is None:
        await cb.answer()
        return
    chat_id = cb.message.chat.id
    data = (cb.data or "").strip()
    parts = data.split(":")
    user = get_user(chat_id)
    _maybe_refresh_username(chat_id, cb.from_user)
    if user is not None:
        user = get_user(chat_id)
    if user is None:
        await cb.answer("Сначала /start", show_alert=True)
        return
    if not _is_vip_user(user):
        await cb.answer("Только для VIP", show_alert=True)
        return

    models: list[str] | tuple[str, ...] = []
    text = _goods_mobile_brands_text()
    markup = _goods_mobile_brands_keyboard(user)

    try:
        if data == "bulk:all":
            models = DEVICE_CATALOG
        elif data == "bulk:apple":
            models = _apple_models()
            text = _goods_apple_lines_text()
            markup = _goods_apple_lines_keyboard(user)
        elif data == "bulk:samsung":
            models = _samsung_models()
            text = _goods_samsung_text()
            markup = _goods_samsung_keyboard(user)
        elif len(parts) == 3 and parts[1] == "ap" and parts[2] in LINE_LABELS:
            line_slug = parts[2]
            models = APPLE_LINES.get(line_slug, ())
            text = _goods_line_pick_text(line_slug)
        elif len(parts) == 3 and parts[1] == "ss" and parts[2] in SAMSUNG_SERIES_LABELS:
            series_slug = parts[2]
            models = _samsung_series_models(series_slug)
            kb = _samsung_series_keyboard(series_slug, user)
            if kb is None:
                await cb.answer("Серия не найдена", show_alert=True)
                return
            text = _samsung_series_text(series_slug)
            markup = kb
        elif len(parts) == 3 and parts[1] == "sg" and parts[2] in SAMSUNG_LINE_LABELS:
            line_slug = parts[2]
            models = SAMSUNG_LINES.get(line_slug, ())
            text = _samsung_line_pick_text(line_slug)
        else:
            await cb.answer("Неизвестное действие", show_alert=True)
            return

        if not models:
            await cb.answer("Нет моделей для выбора", show_alert=True)
            return

        selected, selected_all = _toggle_models(user, models)
        update_keywords(chat_id, selected)
        updated = get_user(chat_id)
        if updated is None:
            await cb.answer("Сначала /start", show_alert=True)
            return

        if data == "bulk:all":
            markup = _goods_mobile_brands_keyboard(updated)
        elif data == "bulk:apple":
            markup = _goods_apple_lines_keyboard(updated)
        elif data == "bulk:samsung":
            markup = _goods_samsung_keyboard(updated)
        elif len(parts) == 3 and parts[1] == "ap" and parts[2] in LINE_LABELS:
            markup = _goods_line_keyboard(updated, parts[2], 0)
        elif len(parts) == 3 and parts[1] == "ss" and parts[2] in SAMSUNG_SERIES_LABELS:
            markup = _samsung_series_keyboard(parts[2], updated)
        elif len(parts) == 3 and parts[1] == "sg" and parts[2] in SAMSUNG_LINE_LABELS:
            markup = _samsung_line_keyboard(updated, parts[2], 0)
        if markup is None:
            await cb.answer("Нет моделей для выбора", show_alert=True)
            return

        await _safe_edit_message(cb, text, reply_markup=markup)
        action = "Выбрано" if selected_all else "Снято"
        await cb.answer(f"{action} моделей: {len(models)}")
    except Exception:
        log.exception("[BULK] error data=%s", data)
        try:
            await cb.answer("Ошибка", show_alert=True)
        except Exception:
            pass


@router.callback_query(lambda c: (c.data or "").startswith("goods:"))
async def on_goods_callback(cb: CallbackQuery) -> None:
    if cb.message is None:
        await cb.answer()
        return
    chat_id = cb.message.chat.id
    data = (cb.data or "").strip()
    user = get_user(chat_id)
    _maybe_refresh_username(chat_id, cb.from_user)
    if user is not None:
        user = get_user(chat_id)

    if user is None:
        await cb.answer("Сначала /start", show_alert=True)
        return

    try:
        if data == "goods:h":
            await _safe_edit_message(
                cb,
                _goods_category_text(),
                reply_markup=_goods_category_keyboard(),
            )
            await cb.answer()
            return

        if data == "goods:m":
            await _safe_edit_message(
                cb,
                _goods_mobile_brands_text(),
                reply_markup=_goods_mobile_brands_keyboard(user),
            )
            await cb.answer()
            return

        if data == "goods:s":
            await _safe_edit_message(
                cb,
                _goods_samsung_text(),
                reply_markup=_goods_samsung_keyboard(user),
            )
            await cb.answer()
            return

        if data == "goods:a":
            await _safe_edit_message(
                cb,
                _goods_apple_lines_text(),
                reply_markup=_goods_apple_lines_keyboard(user),
            )
            await cb.answer()
            return

        if data == "goods:w":
            await _safe_edit_message(
                cb,
                _build_model_list_text(user, "a"),
                reply_markup=_model_list_keyboard(user, "a", page=0),
            )
            await cb.answer()
            return

        if data == "goods:sw":
            await _safe_edit_message(
                cb,
                _build_model_list_text(user, "s"),
                reply_markup=_model_list_keyboard(user, "s", page=0),
            )
            await cb.answer()
            return

        if data.startswith("goods:soon:"):
            await cb.answer("Раздел в разработке.", show_alert=True)
            return

        await cb.answer("Неизвестное действие", show_alert=True)
    except Exception:
        log.exception("[GOODS] error data=%s", data)
        try:
            await cb.answer("Ошибка", show_alert=True)
        except Exception:
            pass


@router.callback_query(lambda c: (c.data or "").startswith("sg:"))
async def on_samsung_series_callback(cb: CallbackQuery) -> None:
    if cb.message is None:
        await cb.answer()
        return
    chat_id = cb.message.chat.id
    user = get_user(chat_id)
    _maybe_refresh_username(chat_id, cb.from_user)
    if user is not None:
        user = get_user(chat_id)
    if user is None:
        await cb.answer("Сначала /start", show_alert=True)
        return

    parts = (cb.data or "").strip().split(":")
    series_slug = parts[1] if len(parts) == 2 else ""
    kb = _samsung_series_keyboard(series_slug, user)
    if kb is None:
        await cb.answer("Неизвестная серия", show_alert=True)
        return
    await _safe_edit_message(
        cb,
        _samsung_series_text(series_slug),
        reply_markup=kb,
    )
    await cb.answer()


@router.callback_query(lambda c: (c.data or "").startswith("st:"))
async def on_samsung_line_callback(cb: CallbackQuery) -> None:
    if cb.message is None:
        await cb.answer()
        return
    chat_id = cb.message.chat.id
    data = (cb.data or "").strip()
    parts = data.split(":")
    if len(parts) != 4 or parts[0] != "st":
        await cb.answer("Ошибка", show_alert=True)
        return
    line_slug, action, arg_raw = parts[1], parts[2], parts[3]
    if line_slug not in SAMSUNG_LINE_LABELS or not arg_raw.isdigit():
        await cb.answer("Ошибка", show_alert=True)
        return
    arg = int(arg_raw)

    user = get_user(chat_id)
    _maybe_refresh_username(chat_id, cb.from_user)
    if user is not None:
        user = get_user(chat_id)
    if user is None:
        await cb.answer("Сначала /start", show_alert=True)
        return

    models = SAMSUNG_LINES.get(line_slug, ())

    try:
        if action == "x":
            await cb.answer()
            return

        if action == "p":
            kb = _samsung_line_keyboard(user, line_slug, arg)
            if kb is None:
                await cb.answer("Нет моделей", show_alert=True)
                return
            await _safe_edit_message(
                cb,
                _samsung_line_pick_text(line_slug),
                reply_markup=kb,
            )
            await cb.answer()
            return

        if action == "t":
            idx = arg
            if idx < 0 or idx >= len(models):
                await cb.answer("Неверная модель", show_alert=True)
                return
            value = models[idx].strip().lower()
            selected = [k.strip().lower() for k in (user.get("keywords") or []) if k.strip()]
            max_kw = _max_keyword_slots(user)
            if value in selected:
                selected.remove(value)
            else:
                if len(selected) >= max_kw:
                    await cb.answer(
                        "Лимит: 5 моделей для обычного пользователя.",
                        show_alert=True,
                    )
                    return
                selected.append(value)
            update_keywords(chat_id, selected)
            updated = get_user(chat_id)
            if updated is None:
                await cb.answer("Сначала /start", show_alert=True)
                return
            page = idx // GOODS_PER_PAGE
            kb = _samsung_line_keyboard(updated, line_slug, page)
            if kb is None:
                await cb.answer()
                return
            await _safe_edit_message(
                cb,
                _samsung_line_pick_text(line_slug),
                reply_markup=kb,
            )
            await cb.answer("Обновлено")
            return

        await cb.answer("Неизвестное действие", show_alert=True)
    except Exception:
        log.exception("[SAMSUNG] error data=%s", data)
        try:
            await cb.answer("Ошибка", show_alert=True)
        except Exception:
            pass


@router.callback_query(lambda c: (c.data or "").startswith("gt:"))
async def on_goods_line_callback(cb: CallbackQuery) -> None:
    if cb.message is None:
        await cb.answer()
        return
    chat_id = cb.message.chat.id
    data = (cb.data or "").strip()
    parts = data.split(":")
    if len(parts) != 4 or parts[0] != "gt":
        await cb.answer("Ошибка", show_alert=True)
        return
    line_slug, action, arg_raw = parts[1], parts[2], parts[3]
    if line_slug not in LINE_LABELS:
        await cb.answer("Ошибка", show_alert=True)
        return
    if not arg_raw.isdigit():
        await cb.answer("Ошибка", show_alert=True)
        return
    arg = int(arg_raw)

    user = get_user(chat_id)
    _maybe_refresh_username(chat_id, cb.from_user)
    if user is not None:
        user = get_user(chat_id)
    if user is None:
        await cb.answer("Сначала /start", show_alert=True)
        return

    models = APPLE_LINES.get(line_slug, ())

    try:
        if action == "x":
            await cb.answer()
            return

        if action == "p":
            page = arg
            kb = _goods_line_keyboard(user, line_slug, page)
            if kb is None:
                await cb.answer("Нет моделей", show_alert=True)
                return
            await _safe_edit_message(
                cb,
                _goods_line_pick_text(line_slug),
                reply_markup=kb,
            )
            await cb.answer()
            return

        if action == "t":
            idx = arg
            if idx < 0 or idx >= len(models):
                await cb.answer("Неверная модель", show_alert=True)
                return
            value = models[idx].strip().lower()
            selected = [k.strip().lower() for k in (user.get("keywords") or []) if k.strip()]
            max_kw = _max_keyword_slots(user)
            if value in selected:
                selected.remove(value)
            else:
                if len(selected) >= max_kw:
                    await cb.answer(
                        "Лимит: 5 моделей для обычного пользователя.",
                        show_alert=True,
                    )
                    return
                selected.append(value)
            update_keywords(chat_id, selected)
            updated = get_user(chat_id)
            if updated is None:
                await cb.answer("Сначала /start", show_alert=True)
                return
            page = idx // GOODS_PER_PAGE
            kb = _goods_line_keyboard(updated, line_slug, page)
            if kb is None:
                await cb.answer()
                return
            await _safe_edit_message(
                cb,
                _goods_line_pick_text(line_slug),
                reply_markup=kb,
            )
            await cb.answer("Обновлено")
            return

        await cb.answer("Неизвестное действие", show_alert=True)
    except Exception:
        log.exception("[GT] error data=%s", data)
        try:
            await cb.answer("Ошибка", show_alert=True)
        except Exception:
            pass


@router.callback_query(lambda c: (c.data or "").startswith("ml:"))
async def on_model_list_callback(cb: CallbackQuery) -> None:
    if cb.message is None:
        await cb.answer()
        return
    chat_id = cb.message.chat.id
    data = (cb.data or "").strip()
    parts = data.split(":")
    if len(parts) != 4 or parts[0] != "ml" or parts[1] not in ("a", "s", "all"):
        await cb.answer("Ошибка", show_alert=True)
        return
    scope, action, arg_raw = parts[1], parts[2], parts[3]
    if not arg_raw.isdigit():
        await cb.answer("Ошибка", show_alert=True)
        return
    arg = int(arg_raw)

    user = get_user(chat_id)
    _maybe_refresh_username(chat_id, cb.from_user)
    if user is not None:
        user = get_user(chat_id)
    if user is None:
        await cb.answer("Сначала /start", show_alert=True)
        return

    models = _models_for_scope(scope)

    try:
        if action == "x":
            await cb.answer()
            return

        if action == "p":
            await _safe_edit_message(
                cb,
                _build_model_list_text(user, scope),
                reply_markup=_model_list_keyboard(user, scope, page=arg),
            )
            await cb.answer()
            return

        if action == "t":
            idx = arg
            if idx < 0 or idx >= len(models):
                await cb.answer("Устройство не найдено", show_alert=True)
                return
            selected = [k.strip().lower() for k in (user.get("keywords") or []) if k.strip()]
            value = models[idx].strip().lower()
            max_kw = _max_keyword_slots(user)
            if value in selected:
                selected.remove(value)
            else:
                if len(selected) >= max_kw:
                    await cb.answer(
                        "Лимит: 5 моделей для обычного пользователя.",
                        show_alert=True,
                    )
                    return
                selected.append(value)
            update_keywords(chat_id, selected)
            updated = get_user(chat_id)
            if updated is None:
                await cb.answer("Сначала /start", show_alert=True)
                return
            page = idx // PER_PAGE
            await _safe_edit_message(
                cb,
                _build_model_list_text(updated, scope),
                reply_markup=_model_list_keyboard(updated, scope, page=page),
            )
            await cb.answer("Обновлено")
            return

        await cb.answer("Неизвестное действие", show_alert=True)
    except Exception:
        log.exception("[MODEL_LIST] error data=%s", data)
        try:
            await cb.answer("Ошибка", show_alert=True)
        except Exception:
            pass


@router.callback_query(lambda c: (c.data or "") == "kw:x")
async def on_keywords_nav_noop(cb: CallbackQuery) -> None:
    await cb.answer()


@router.callback_query(lambda c: (c.data or "").startswith("kw:page:"))
async def on_keywords_page(cb: CallbackQuery) -> None:
    if cb.message is None:
        await cb.answer()
        return
    chat_id = cb.message.chat.id
    user = get_user(chat_id)
    _maybe_refresh_username(chat_id, cb.from_user)
    if user is not None:
        user = get_user(chat_id)
    if user is None:
        await cb.answer("Сначала /start", show_alert=True)
        return
    page_raw = (cb.data or "").split(":")[-1]
    page = int(page_raw) if page_raw.isdigit() else 0
    await _safe_edit_message(
        cb,
        _build_keywords_text(user),
        reply_markup=_keywords_keyboard(user, page=page),
    )
    await cb.answer()


@router.callback_query(lambda c: (c.data or "").startswith("kw:toggle:"))
async def on_keywords_toggle(cb: CallbackQuery) -> None:
    if cb.message is None:
        await cb.answer()
        return
    chat_id = cb.message.chat.id
    user = get_user(chat_id)
    _maybe_refresh_username(chat_id, cb.from_user)
    if user is not None:
        user = get_user(chat_id)
    if user is None:
        await cb.answer("Сначала /start", show_alert=True)
        return

    idx_raw = (cb.data or "").split(":")[-1]
    if not idx_raw.isdigit():
        await cb.answer("Ошибка выбора", show_alert=True)
        return
    idx = int(idx_raw)
    if idx < 0 or idx >= len(DEVICE_CATALOG):
        await cb.answer("Устройство не найдено", show_alert=True)
        return

    selected = [k.strip().lower() for k in (user.get("keywords") or []) if k.strip()]
    value = DEVICE_CATALOG[idx].strip().lower()
    max_kw = _max_keyword_slots(user)
    if value in selected:
        selected.remove(value)
    else:
        if len(selected) >= max_kw:
            await cb.answer(
                "Лимит: 5 моделей для обычного пользователя.",
                show_alert=True,
            )
            return
        selected.append(value)

    update_keywords(cb.message.chat.id, selected)
    updated = get_user(cb.message.chat.id)
    if updated is None:
        await cb.answer("Сначала /start", show_alert=True)
        return
    page = idx // PER_PAGE
    await _safe_edit_message(
        cb,
        _build_keywords_text(updated),
        reply_markup=_keywords_keyboard(updated, page=page),
    )
    await cb.answer("Обновлено")


@router.callback_query(lambda c: (c.data or "") == "kw:done")
async def on_keywords_done(cb: CallbackQuery) -> None:
    if cb.message is None:
        await cb.answer()
        return
    chat_id = cb.message.chat.id
    user = get_user(chat_id)
    _maybe_refresh_username(chat_id, cb.from_user)
    if user is not None:
        user = get_user(chat_id)
    uid = cb.from_user.id if cb.from_user else 0
    if user is None:
        await cb.answer("Сначала /start", show_alert=True)
        return
    selected = user.get("keywords") or []
    await _safe_edit_message(
        cb,
        _main_home_text(user, is_new=False)
        + "\n\n✅ <b>Товары сохранены.</b> Выбрано: "
        + str(len(selected))
        + (f"\n<code>{', '.join(selected)}</code>" if selected else ""),
        reply_markup=_main_menu_keyboard(is_admin=_is_admin(uid), user=user),
    )
    await cb.answer("Сохранено")


@router.callback_query(lambda c: (c.data or "").startswith("adm:"))
async def on_admin_callback(cb: CallbackQuery, state: FSMContext) -> None:
    uid = cb.from_user.id if cb.from_user else 0
    if not _is_admin(uid):
        await cb.answer("Нет доступа", show_alert=True)
        return
    if cb.message is None:
        await cb.answer()
        return

    data = (cb.data or "").strip()
    parts = data.split(":")

    try:
        if data == "adm:h":
            await state.clear()
            await _safe_edit_message(
                cb,
                _admin_home_text(),
                reply_markup=_admin_main_keyboard(),
            )
            await cb.answer()
            return

        if data == "adm:x":
            await cb.answer()
            return

        if data == "adm:st":
            await _safe_edit_message(
                cb,
                _admin_stats_text(),
                reply_markup=_admin_stats_keyboard(),
            )
            await cb.answer()
            return

        if data == "adm:promo":
            await state.clear()
            await _safe_edit_message(
                cb,
                _admin_promos_text(),
                reply_markup=_admin_promos_keyboard(),
            )
            await cb.answer()
            return

        if data == "adm:promo:list":
            await state.clear()
            await _safe_edit_message(
                cb,
                _promo_codes_list_text(),
                reply_markup=_admin_promos_keyboard(),
            )
            await cb.answer()
            return

        if data == "adm:promo:random":
            await state.set_state(AdminPromoState.waiting_random)
            await _safe_edit_message(
                cb,
                "🎲 <b>Случайные промокоды</b>\n\n"
                "Введите количество промокодов и срок VIP в днях через пробел.\n"
                "Пример: <code>5 7</code>",
                reply_markup=_admin_promos_keyboard(),
            )
            await cb.answer()
            return

        if data == "adm:promo:manual":
            await state.set_state(AdminPromoState.waiting_manual)
            await _safe_edit_message(
                cb,
                "✍️ <b>Промокод вручную</b>\n\n"
                "Введите название, количество использований и срок VIP в днях через пробел.\n"
                "Пример: <code>SALE2026 10 7</code>",
                reply_markup=_admin_promos_keyboard(),
            )
            await cb.answer()
            return

        if len(parts) == 3 and parts[0] == "adm" and parts[1] == "us" and parts[2].isdigit():
            page = int(parts[2])
            await _safe_edit_message(
                cb,
                _admin_users_page_text(page),
                reply_markup=_admin_users_keyboard(page),
            )
            await cb.answer()
            return

        if len(parts) == 3 and parts[0] == "adm" and parts[1] == "u" and parts[2].lstrip("-").isdigit():
            target_id = int(parts[2])
            u = get_user(target_id)
            if u is None:
                await cb.answer("Пользователь не найден", show_alert=True)
                return
            card = await format_user_status_html(cb.bot, u)
            await _safe_edit_message(
                cb,
                card,
                reply_markup=_admin_user_keyboard(target_id),
            )
            await cb.answer()
            return

        if len(parts) == 4 and parts[0] == "adm" and parts[1] == "vip" and parts[2].lstrip("-").isdigit() and parts[3].isdigit():
            target_id = int(parts[2])
            days = max(1, int(parts[3]))
            if get_user(target_id) is None:
                await cb.answer("Пользователь не найден", show_alert=True)
                return
            set_vip(target_id, days=days)
            u = get_user(target_id)
            if u is None:
                await cb.answer("Ошибка сохранения", show_alert=True)
                return
            card = await format_user_status_html(cb.bot, u)
            await _safe_edit_message(
                cb,
                card,
                reply_markup=_admin_user_keyboard(target_id),
            )
            await cb.answer(f"VIP +{days} дн.")
            return

        if len(parts) == 3 and parts[0] == "adm" and parts[1] == "unv" and parts[2].lstrip("-").isdigit():
            target_id = int(parts[2])
            revoke_vip(target_id)
            u = get_user(target_id)
            if u is None:
                await cb.answer("Пользователь не найден", show_alert=True)
                return
            card = await format_user_status_html(cb.bot, u)
            await _safe_edit_message(
                cb,
                card,
                reply_markup=_admin_user_keyboard(target_id),
            )
            await cb.answer("VIP снят")
            return

        if data == "adm:mp:go":
            n = clear_market_prices()
            await _safe_edit_message(
                cb,
                f"✅ Готово. Удалено записей о ценах: <b>{n}</b>\n\n" + _admin_home_text(),
                reply_markup=_admin_main_keyboard(),
            )
            await cb.answer("Сброшено")
            return

        if data == "adm:mp":
            await _safe_edit_message(
                cb,
                "🧹 <b>Сброс глобальных цен рынка</b>\n\n"
                "Будут удалены записи из <code>market_prices</code> "
                "(средняя цена для VIP начнёт накапливаться заново).\n\n"
                "Подтверди действие:",
                reply_markup=_admin_market_confirm_keyboard(),
            )
            await cb.answer()
            return

        await cb.answer("Неизвестное действие", show_alert=True)
    except Exception:
        log.exception("[ADM] callback error data=%s", data)
        try:
            await cb.answer("Ошибка", show_alert=True)
        except Exception:
            pass


@router.message(AdminPromoState.waiting_random, F.text, ~F.text.startswith("/"))
async def on_admin_random_promos_text(msg: Message, state: FSMContext) -> None:
    uid = _actor_user_id(msg)
    if not _is_admin(uid):
        await state.clear()
        return

    parts = (msg.text or "").strip().split()
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        await msg.answer(
            "Введите два числа через пробел: количество промокодов и срок VIP в днях.\n"
            "Пример: <code>5 7</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    count = int(parts[0])
    days = int(parts[1])
    if not 1 <= count <= 100 or not 1 <= days <= 3650:
        await msg.answer(
            "Количество должно быть от 1 до 100, срок VIP — от 1 до 3650 дней.",
            parse_mode=ParseMode.HTML,
        )
        return

    created: list[str] = []
    attempts = 0
    while len(created) < count and attempts < count * 10:
        attempts += 1
        code = _generate_promo_code()
        if create_promo_code(code, vip_days=days, max_uses=1):
            created.append(code)

    if len(created) != count:
        await msg.answer("Не удалось создать нужное количество промокодов. Попробуйте ещё раз.")
        return

    await state.clear()
    await msg.answer("успешно")
    await msg.answer(
        _promo_codes_list_text(),
        reply_markup=_admin_promos_keyboard(),
        parse_mode=ParseMode.HTML,
    )


@router.message(AdminPromoState.waiting_manual, F.text, ~F.text.startswith("/"))
async def on_admin_manual_promo_text(msg: Message, state: FSMContext) -> None:
    uid = _actor_user_id(msg)
    if not _is_admin(uid):
        await state.clear()
        return

    parts = (msg.text or "").strip().split()
    if len(parts) != 3 or not parts[1].isdigit() or not parts[2].isdigit():
        await msg.answer(
            "Введите название, количество использований и срок VIP в днях через пробел.\n"
            "Пример: <code>SALE2026 10 7</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    code = parts[0]
    max_uses = int(parts[1])
    days = int(parts[2])
    if not 1 <= max_uses <= 1_000_000 or not 1 <= days <= 3650:
        await msg.answer(
            "Количество использований должно быть от 1, срок VIP — от 1 до 3650 дней.",
            parse_mode=ParseMode.HTML,
        )
        return

    if not create_promo_code(code, vip_days=days, max_uses=max_uses):
        await msg.answer(
            "Такой промокод уже существует или название пустое. Введите данные заново.",
            parse_mode=ParseMode.HTML,
        )
        return

    await state.clear()
    await msg.answer("успешно")
    await msg.answer(
        _promo_codes_list_text(),
        reply_markup=_admin_promos_keyboard(),
        parse_mode=ParseMode.HTML,
    )


@router.message(CustomPriceState.waiting_price, F.text, ~F.text.startswith("/"))
async def on_custom_price_text(msg: Message, state: FSMContext) -> None:
    chat_id = msg.chat.id
    _maybe_refresh_username(chat_id, msg.from_user)
    user = get_user(chat_id)
    if user is None:
        await state.clear()
        await msg.answer("Сначала нажми <code>/start</code>.", parse_mode=ParseMode.HTML)
        return
    if not _is_vip_user(user):
        await state.clear()
        await msg.answer("Индивидуальная цена доступна только для VIP.", parse_mode=ParseMode.HTML)
        return

    raw = (msg.text or "").strip().replace(" ", "")
    if not raw.isdigit():
        await msg.answer(
            "Введите цену одним числом, например <code>1200</code>.",
            parse_mode=ParseMode.HTML,
        )
        return
    price = int(raw)
    if not 1 <= price <= 10_000_000:
        await msg.answer(
            "Цена должна быть от 1 до 10 000 000 р. Введите значение заново.",
            parse_mode=ParseMode.HTML,
        )
        return

    update_max_price(chat_id, price)
    await state.clear()
    updated = get_user(chat_id)
    await msg.answer(
        _price_screen_text(updated),
        reply_markup=_price_presets_keyboard(updated),
        parse_mode=ParseMode.HTML,
    )


@router.message(PromoCodeState.waiting_code, F.text, ~F.text.startswith("/"))
async def on_promo_code_text(msg: Message, state: FSMContext) -> None:
    chat_id = msg.chat.id
    _maybe_refresh_username(chat_id, msg.from_user)
    user = get_user(chat_id)
    if user is None:
        await state.clear()
        await msg.answer(
            "Сначала нажми <code>/start</code>.",
            parse_mode=ParseMode.HTML,
        )
        return

    status, days = redeem_promo_code(chat_id, msg.text or "")
    if status == "ok" and days is not None:
        set_vip(chat_id, days=days)
        await state.clear()
        updated_user = get_user(chat_id)
        uid = _actor_user_id(msg)
        await msg.answer(
            f"✅ Промокод активирован. VIP на <b>{days}</b> дн.",
            reply_markup=_main_menu_keyboard(is_admin=_is_admin(uid), user=updated_user),
            parse_mode=ParseMode.HTML,
        )
        return

    if status == "already_used":
        await msg.answer(
            "❌ Этот промокод уже использован. Введите промокод заново:",
            reply_markup=_promo_back_keyboard(),
            parse_mode=ParseMode.HTML,
        )
        return

    await msg.answer(
        "❌ Такого промокода нет. Введите промокод заново:",
        reply_markup=_promo_back_keyboard(),
        parse_mode=ParseMode.HTML,
    )


@router.message(F.text)
async def on_any_text(msg: Message) -> None:
    if msg.text and msg.text.startswith("/"):
        await msg.answer(
            "Команды, кроме <code>/start</code>, не используются.\n"
            "Нажми <code>/start</code> — откроется меню с кнопками.",
            parse_mode=ParseMode.HTML,
        )
        return
    chat_id = msg.chat.id
    _maybe_refresh_username(chat_id, msg.from_user)
    user = get_user(chat_id)
    uid = _actor_user_id(msg)
    hint = (
        "Пиши сюда не нужно — всё через кнопки в меню.\n"
        "Нажми <code>/start</code>, если меню пропало."
    )
    if user and not user.get("active"):
        hint += "\n\nРассылка выключена — в меню кнопка <b>«Включить рассылку»</b>."
    await msg.answer(
        hint,
        reply_markup=_main_menu_keyboard(is_admin=_is_admin(uid), user=user) if user else None,
        parse_mode=ParseMode.HTML,
    )


def _build_keywords_text(user: dict) -> str:
    selected = user.get("keywords") or []
    role = user.get("role")
    limit = "без лимита" if role == "vip" else "до 5"
    return (
        f"{_GOODS_CRUMB} › <b>Мобильные</b> › <b>Все модели</b>\n\n"
        "Нажми на модель — вкл/выкл. Внизу <b>«Готово»</b> — в главное меню.\n"
        f"Лимит ручного выбора: <b>{limit}</b>\n\n"
        f"Выбрано: <b>{len(selected)}</b>\n"
        + ("<code>" + ", ".join(selected) + "</code>" if selected else "Пока пусто.")
    )


def _build_model_list_text(user: dict, scope: str) -> str:
    selected = user.get("keywords") or []
    role = user.get("role")
    limit = "без лимита" if role == "vip" else "до 5"
    models = _models_for_scope(scope)
    selected_in_scope = {
        k.strip().lower()
        for k in selected
        if k.strip().lower() in {m.strip().lower() for m in models}
    }
    return (
        f"{_GOODS_CRUMB} › <b>Мобильные</b> › {_model_list_title(scope)}\n\n"
        "Нажми на модель — вкл/выкл. Внизу <b>«Готово»</b> — в главное меню.\n"
        f"Лимит ручного выбора: <b>{limit}</b>\n\n"
        f"Выбрано здесь: <b>{len(selected_in_scope)}</b> из <b>{len(models)}</b>\n"
        f"Всего выбрано: <b>{len(selected)}</b>"
    )


def _model_list_keyboard(user: dict, scope: str, *, page: int) -> InlineKeyboardMarkup:
    models = _models_for_scope(scope)
    total_pages = max(1, (len(models) + PER_PAGE - 1) // PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    start = page * PER_PAGE
    chunk = models[start : start + PER_PAGE]
    selected = {k.strip().lower() for k in (user.get("keywords") or []) if k.strip()}

    rows: list[list[InlineKeyboardButton]] = []
    for i in range(0, len(chunk), 2):
        row: list[InlineKeyboardButton] = []
        for j in range(2):
            if i + j >= len(chunk):
                continue
            idx = start + i + j
            item = chunk[i + j]
            mark = "✅ " if item.lower() in selected else ""
            row.append(InlineKeyboardButton(text=f"{mark}{item}", callback_data=f"ml:{scope}:t:{idx}"))
        if row:
            rows.append(row)

    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"ml:{scope}:p:{page - 1}"))
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data=f"ml:{scope}:x:0"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"ml:{scope}:p:{page + 1}"))
    rows.append(nav)
    if _is_vip_user(user):
        rows.append([InlineKeyboardButton(text="📋 Выбрать все модели", callback_data=_model_list_bulk_callback(scope))])
    rows.append(
        [
            InlineKeyboardButton(text="Готово ✅", callback_data="kw:done"),
            _model_list_back_button(scope),
        ]
    )
    rows.append([InlineKeyboardButton(text="🏠 В меню", callback_data="nav:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _keywords_keyboard(user: dict, *, page: int) -> InlineKeyboardMarkup:
    total_pages = max(1, (len(DEVICE_CATALOG) + PER_PAGE - 1) // PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    start = page * PER_PAGE
    chunk = DEVICE_CATALOG[start : start + PER_PAGE]
    selected = {k.strip().lower() for k in (user.get("keywords") or []) if k.strip()}

    rows: list[list[InlineKeyboardButton]] = []
    for i in range(0, len(chunk), 2):
        row: list[InlineKeyboardButton] = []
        for j in range(2):
            if i + j >= len(chunk):
                continue
            idx = start + i + j
            item = chunk[i + j]
            mark = "✅ " if item.lower() in selected else ""
            row.append(
                InlineKeyboardButton(text=f"{mark}{item}", callback_data=f"kw:toggle:{idx}")
            )
        if row:
            rows.append(row)

    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"kw:page:{page - 1}"))
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="kw:x"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"kw:page:{page + 1}"))
    rows.append(nav)
    if _is_vip_user(user):
        rows.append([InlineKeyboardButton(text="📋 Выбрать все модели", callback_data="bulk:all")])
    rows.append(
        [
            InlineKeyboardButton(text="Готово ✅", callback_data="kw:done"),
            InlineKeyboardButton(text="⬅️ К линейкам", callback_data="goods:a"),
        ]
    )
    rows.append([InlineKeyboardButton(text="🏠 В меню", callback_data="nav:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
