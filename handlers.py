import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from config import ADMIN_IDS, DEVICE_CATALOG, MAX_PRICE_PRESETS, VIP_PRICE_USD
from goods_tree import (
    APPLE_LINES,
    GOODS_PER_PAGE,
    LINE_BASIC,
    LINE_LABELS,
    LINE_MAX,
    LINE_PRO,
)
from db import (
    add_user,
    clear_market_prices,
    count_users_active,
    count_users_total,
    count_users_vip,
    get_user,
    list_users_page,
    revoke_vip,
    set_active,
    set_vip,
    update_keywords,
    update_max_price,
    update_vip_feed_mode,
)
from formatter import HELP_TEXT, format_status

log = logging.getLogger(__name__)
router = Router()
PER_PAGE = 8
ADM_USERS_PER_PAGE = 6

_GOODS_CRUMB = "📦 <b>Товары</b>"


def _max_keyword_slots(user: dict) -> int:
    return 9999 if user.get("role") == "vip" else 5


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


def _goods_mobile_brands_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Apple", callback_data="goods:a"),
                InlineKeyboardButton(text="Samsung", callback_data="goods:s"),
            ],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="goods:h")],
        ]
    )


def _goods_samsung_text() -> str:
    return (
        f"{_GOODS_CRUMB} › <b>Мобильные</b> › <b>Samsung</b>\n\n"
        "Серии <b>Galaxy S</b>, <b>A</b> и другие появятся в следующих версиях.\n"
        "Сейчас поиск Kufar и фильтры заточены под <b>iPhone</b> — выберите Apple или полный список моделей."
    )


def _goods_apple_lines_text() -> str:
    return (
        f"{_GOODS_CRUMB} › <b>Мобильные</b> › <b>Apple</b>\n\n"
        "Выберите <b>линейку</b>, затем отметьте модели."
    )


def _goods_apple_lines_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=f"🍎 {LINE_LABELS[LINE_BASIC]}", callback_data=f"gt:{LINE_BASIC}:p:0"),
                InlineKeyboardButton(text=f"🍎 {LINE_LABELS[LINE_PRO]}", callback_data=f"gt:{LINE_PRO}:p:0"),
            ],
            [
                InlineKeyboardButton(text=f"🍎 {LINE_LABELS[LINE_MAX]}", callback_data=f"gt:{LINE_MAX}:p:0"),
            ],
            [
                InlineKeyboardButton(text="📋 Все модели списком", callback_data="goods:w"),
            ],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="goods:m")],
        ]
    )


def _goods_samsung_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="goods:m")],
        ]
    )


def _goods_line_pick_text(line_slug: str) -> str:
    title = LINE_LABELS.get(line_slug, line_slug)
    return (
        f"{_GOODS_CRUMB} › <b>Мобильные</b> › <b>Apple</b> › <b>{title}</b>\n\n"
        "Нажмите на модель — <b>вкл/выкл</b>.\n"
        f"Лимит для обычного пользователя: до {_max_keyword_slots({'role': 'regular'})} позиций.\n"
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
        label = f"{act}{role_icon} {cid} · {n_kw} устр."
        if len(label) > 58:
            label = f"{act}{role_icon} {cid}"
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


def _admin_user_card_text(u: dict) -> str:
    return format_status(u)


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
                "🔥 <b>VIP-поток:</b> только объявления ниже средней цены по рынку (все iPhone). "
                "Повторное нажатие кнопки — выключить.",
            ]
        elif mode == "exchange":
            lines += [
                "",
                "🔄 <b>VIP-поток:</b> только объявления про обмен (все iPhone). "
                "Повторное нажатие кнопки — выключить.",
            ]
        else:
            lines += [
                "",
                "⭐ <b>VIP:</b> дополнительно можно включить потоки «ниже рынка» или «только обмен» "
                "(все iPhone, не только выбранные модели) — кнопками ниже.",
            ]
    lines += ["", "Навигация — <b>кнопками</b>. Пропало меню — <code>/start</code>."]
    return "\n".join(lines)


def _main_menu_keyboard(*, is_admin: bool, user: dict | None = None) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
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
        t_ex = "🔄 Только обмен (бета)"
        if mode == "exchange":
            t_ex = "🔄 Обмен (бета) ✓"
        rows.append(
            [
                InlineKeyboardButton(text=t_bm, callback_data="nav:vipf:bm"),
                InlineKeyboardButton(text=t_ex, callback_data="nav:vipf:ex"),
            ]
        )
    bottom = [
        InlineKeyboardButton(text="❓ Помощь", callback_data="nav:help"),
    ]
    if user and user.get("active"):
        bottom.append(InlineKeyboardButton(text="⛔ Отписаться", callback_data="nav:stop"))
    rows.append(bottom)
    if is_admin:
        rows.append([InlineKeyboardButton(text="🔐 Админ-панель", callback_data="nav:admin")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _nav_back_home_button() -> list[InlineKeyboardButton]:
    return [InlineKeyboardButton(text="⬅️ В меню", callback_data="nav:home")]


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
        "(все iPhone с листинга, не только выбранные модели) — кнопками в главном меню."
    )


@router.message(CommandStart())
async def on_start(msg: Message) -> None:
    chat_id = msg.chat.id
    is_new = add_user(chat_id)
    log.info("[START] chat_id=%s new=%s", chat_id, is_new)
    user = get_user(chat_id)
    uid = _actor_user_id(msg)
    await msg.answer(
        _main_home_text(user, is_new=is_new),
        reply_markup=_main_menu_keyboard(is_admin=_is_admin(uid), user=user),
        parse_mode=ParseMode.HTML,
    )


@router.message(Command("admin"))
async def on_admin(msg: Message) -> None:
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
async def on_nav_callback(cb: CallbackQuery) -> None:
    if cb.message is None:
        await cb.answer()
        return
    chat_id = cb.message.chat.id
    uid = cb.from_user.id if cb.from_user else 0
    data = (cb.data or "").strip()
    parts = data.split(":")

    user = get_user(chat_id)
    is_admin = _is_admin(uid)

    try:
        if data == "nav:home":
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
                "Только ниже рынка (все iPhone)"
                if new_mode == "below_market"
                else ("Только обмен (все iPhone)" if new_mode == "exchange" else "Обычная рассылка")
            )
            await cb.answer(hint)
            return

        if data == "nav:status":
            await _safe_edit_message(
                cb,
                format_status(user),
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
            await _safe_edit_message(
                cb,
                _price_screen_text(user),
                reply_markup=_price_presets_keyboard(user),
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


@router.callback_query(lambda c: (c.data or "").startswith("goods:"))
async def on_goods_callback(cb: CallbackQuery) -> None:
    if cb.message is None:
        await cb.answer()
        return
    chat_id = cb.message.chat.id
    data = (cb.data or "").strip()
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
                reply_markup=_goods_mobile_brands_keyboard(),
            )
            await cb.answer()
            return

        if data == "goods:s":
            await _safe_edit_message(
                cb,
                _goods_samsung_text(),
                reply_markup=_goods_samsung_keyboard(),
            )
            await cb.answer()
            return

        if data == "goods:a":
            await _safe_edit_message(
                cb,
                _goods_apple_lines_text(),
                reply_markup=_goods_apple_lines_keyboard(),
            )
            await cb.answer()
            return

        if data == "goods:w":
            await _safe_edit_message(
                cb,
                _build_keywords_text(user),
                reply_markup=_keywords_keyboard(user, page=0),
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


@router.callback_query(lambda c: (c.data or "") == "kw:x")
async def on_keywords_nav_noop(cb: CallbackQuery) -> None:
    await cb.answer()


@router.callback_query(lambda c: (c.data or "").startswith("kw:page:"))
async def on_keywords_page(cb: CallbackQuery) -> None:
    if cb.message is None:
        await cb.answer()
        return
    user = get_user(cb.message.chat.id)
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
    user = get_user(cb.message.chat.id)
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
    user = get_user(cb.message.chat.id)
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
async def on_admin_callback(cb: CallbackQuery) -> None:
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
            await _safe_edit_message(
                cb,
                _admin_user_card_text(u),
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
            await _safe_edit_message(
                cb,
                _admin_user_card_text(u),
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
            await _safe_edit_message(
                cb,
                _admin_user_card_text(u),
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


@router.message(F.text)
async def on_any_text(msg: Message) -> None:
    if msg.text and msg.text.startswith("/"):
        await msg.answer(
            "Команды, кроме <code>/start</code> и (для админа) <code>/admin</code>, не используются.\n"
            "Нажми <code>/start</code> — откроется меню с кнопками.",
            parse_mode=ParseMode.HTML,
        )
        return
    user = get_user(msg.chat.id)
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
        f"{_GOODS_CRUMB} › <b>Мобильные</b> › <b>Apple</b> › <b>Все модели</b>\n\n"
        "Нажми на модель — вкл/выкл. Внизу <b>«Готово»</b> — в главное меню.\n"
        f"Лимит: <b>{limit}</b>\n\n"
        f"Выбрано: <b>{len(selected)}</b>\n"
        + ("<code>" + ", ".join(selected) + "</code>" if selected else "Пока пусто.")
    )


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
    rows.append(
        [
            InlineKeyboardButton(text="Готово ✅", callback_data="kw:done"),
            InlineKeyboardButton(text="⬅️ К линейкам", callback_data="goods:a"),
        ]
    )
    rows.append([InlineKeyboardButton(text="🏠 В меню", callback_data="nav:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
