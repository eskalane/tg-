"""
Telegram-бот: проверка подписки на канал, главное меню (инлайн-кнопки), промокод glory.
Заполните .env по образцу .env.example и установите зависимости: pip install -r requirements.txt
"""

from __future__ import annotations

import html
import json
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
)
from telegram.constants import ChatMemberStatus, ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

_ROOT = Path(__file__).resolve().parent
_ENV_FILE = _ROOT / ".env"
load_dotenv(_ENV_FILE)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def _env_var(name: str, default: str = "") -> str:
    raw = os.environ.get(name)
    if raw is None:
        return default
    v = str(raw).strip()
    if len(v) >= 2 and v[0] in "\"'" and v[0] == v[-1]:
        v = v[1:-1].strip()
    return v


BOT_TOKEN = _env_var("BOT_TOKEN")
CHANNEL_ID = _env_var("CHANNEL_ID")
CHANNEL_URL = _env_var("CHANNEL_URL")
MANAGER_USERNAME = _env_var("MANAGER_USERNAME", "modsdev").lstrip("@")
WELCOME_PHOTO = _env_var("WELCOME_PHOTO")

# Фото «2» по умолчанию — assets/menu_photo.png (положите свой файл при необходимости)
DEFAULT_BANNER = _ROOT / "assets" / "menu_photo.png"

BTN_PROMO = "/promo glory❤"
BTN_MODS = "Mods🧟"
BTN_SUPPORT = "связаться с тех.поддержкой🔊"

CB_PROMO = "menu_promo"
CB_MODS = "menu_mods"
CB_SUPPORT = "menu_support"
CB_MAIN = "menu_main"
CB_CHECK_SUB = "check_sub"

# id модов = ключ в callback mod_<id> и dl_<id>
MOD_ID_GLORY = "glory_redux_v1"
MOD_ID_ECHO = "echo_redux"

_COUNTS_FILE = _ROOT / "data" / "download_counts.json"


def _load_download_counts() -> dict[str, int]:
    if not _COUNTS_FILE.is_file():
        return {}
    try:
        raw = json.loads(_COUNTS_FILE.read_text(encoding="utf-8"))
        return {str(k): int(v) for k, v in raw.items() if isinstance(v, (int, float))}
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return {}


def _save_download_counts(counts: dict[str, int]) -> None:
    _COUNTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    _COUNTS_FILE.write_text(
        json.dumps(counts, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def increment_mod_downloads(mod_id: str) -> int:
    counts = _load_download_counts()
    counts[mod_id] = counts.get(mod_id, 0) + 1
    _save_download_counts(counts)
    return counts[mod_id]


def get_mod_downloads(mod_id: str) -> int:
    return _load_download_counts().get(mod_id, 0)


def _mods_registry() -> dict[str, dict[str, str]]:
    """Ссылки из .env. Пустое значение = «обзора нет» / нет ссылки на скачивание."""
    return {
        MOD_ID_GLORY: {
            "title": "Glory Redux V1",
            "overview_url": _env_var("MOD_GLORY_REDUX_V1_OVERVIEW_URL", ""),
            "download_url": _env_var("MOD_GLORY_REDUX_V1_DOWNLOAD_URL", ""),
        },
        MOD_ID_ECHO: {
            "title": "ECHO REDUX",
            "overview_url": _env_var("MOD_ECHO_REDUX_OVERVIEW_URL", ""),
            "download_url": _env_var("MOD_ECHO_REDUX_DOWNLOAD_URL", ""),
        },
    }


MODS = _mods_registry()


def _link_usable(url: str) -> bool:
    u = (url or "").strip()
    return len(u) > 8 and (u.startswith("https://") or u.startswith("http://"))


def mod_caption_html(mod_id: str, downloads: int) -> str:
    m = MODS[mod_id]
    title = html.escape(m["title"])
    overview_raw = (m.get("overview_url") or "").strip()
    dl_raw = (m.get("download_url") or "").strip()

    if _link_usable(overview_raw):
        ou = html.escape(overview_raw, quote=True)
        overview_line = f'<b>Обзор:</b> <a href="{ou}">ссылка</a>'
    else:
        overview_line = "<b>Обзор:</b> обзора нет"

    lines = [f"<b>{title}</b>", "", overview_line, ""]

    if _link_usable(dl_raw):
        du = html.escape(dl_raw, quote=True)
        lines.append(f'<b>Скачать:</b> <a href="{du}">ссылка</a>')
        lines.append("")
    else:
        lines.append("<b>Скачать:</b> ссылки на скачивание нет")
        lines.append("")

    lines.append(f"<b>Счётчик скачиваний:</b> {downloads}")
    if _link_usable(dl_raw):
        lines.append("")
        lines.append("<i>После скачивания нажми «Учесть скачивание» под фото.</i>")
    return "\n".join(lines)


def _banner_path() -> Path | None:
    if WELCOME_PHOTO:
        p = Path(WELCOME_PHOTO)
        if not p.is_absolute():
            p = _ROOT / p
        if p.is_file():
            return p
    if DEFAULT_BANNER.is_file():
        return DEFAULT_BANNER
    logger.warning("Файл баннера не найден: %s — отправляю только текст.", DEFAULT_BANNER)
    return None


def _strip_vs16(s: str) -> str:
    return s.replace("\uFE0F", "").strip()


def _is_promo_button(text: str) -> bool:
    t = _strip_vs16(text)
    if t == _strip_vs16(BTN_PROMO):
        return True
    low = t.lower()
    return "promo" in low and "glory" in low


def _manager_url() -> str:
    return f"https://t.me/{MANAGER_USERNAME}"


PROMO_TEXT = (
    "Введя промокод <b>glory</b> на любом из серверов помимо 50.000$ и 7 дней "
    "Majestic Premium'a вы получите от нас 100.000$ на 15/16 сервере.\n\n"
    "<b>Как ввести промокод?</b>\n\n"
    'Через браузер <a href="https://majestic-rp.ru/register?utm_campaign=glory">'
    "https://majestic-rp.ru/register?utm_campaign=glory</a> или в игре: при "
    "регистрации укажите промокод <b>glory</b>, либо в чате командой "
    "<code>/promo glory</code>.\n\n"
    "<b>Как получить награду?</b>\n\n"
    "Нажмите «получить $$$» → вас перебросит в чат с менеджером. Сообщите ему:\n\n"
    "1. Ник в игре и статик #\n"
    "2. Номер сервера (15/16)\n"
    "3. Банковский счёт (инвентарь → наведите курсор на карту)\n"
    "4. Скриншот введённого промокода\n\n"
    "После этого ожидайте зачисление денег."
)

MODS_LIST_TEXT = "Выбери модификацию:"


def mods_list_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Glory Redux V1", callback_data=f"mod_{MOD_ID_GLORY}")],
            [InlineKeyboardButton("ECHO REDUX", callback_data=f"mod_{MOD_ID_ECHO}")],
            [InlineKeyboardButton("« В главное меню", callback_data=CB_MAIN)],
        ]
    )


def mod_detail_keyboard(mod_id: str) -> InlineKeyboardMarkup:
    mod = MODS[mod_id]
    dl = (mod.get("download_url") or "").strip()
    rows: list[list[InlineKeyboardButton]] = []
    if _link_usable(dl):
        rows.append([InlineKeyboardButton("Скачать", url=dl)])
        rows.append(
            [InlineKeyboardButton("Учесть скачивание", callback_data=f"cnt_{mod_id}")]
        )
    else:
        rows.append([InlineKeyboardButton("Скачать", callback_data=f"dl_{mod_id}")])
    rows.append([InlineKeyboardButton("« К списку модов", callback_data=CB_MODS)])
    rows.append([InlineKeyboardButton("« В главное меню", callback_data=CB_MAIN)])
    return InlineKeyboardMarkup(rows)


def main_menu_inline_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(BTN_PROMO, callback_data=CB_PROMO)],
            [InlineKeyboardButton(BTN_MODS, callback_data=CB_MODS)],
            [InlineKeyboardButton(BTN_SUPPORT, callback_data=CB_SUPPORT)],
        ]
    )


def promo_reply_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("получить $$$", url=_manager_url())],
            [InlineKeyboardButton("« В главное меню", callback_data=CB_MAIN)],
        ]
    )


def support_reply_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    f"Чат с тех. поддержкой @{MANAGER_USERNAME}",
                    url=_manager_url(),
                )
            ],
            [InlineKeyboardButton("« В главное меню", callback_data=CB_MAIN)],
        ]
    )


def not_subscribed_keyboard() -> InlineKeyboardMarkup:
    rows = []
    if CHANNEL_URL:
        rows.append([InlineKeyboardButton("Подписаться на канал", url=CHANNEL_URL)])
    rows.append([InlineKeyboardButton("Проверить подписку", callback_data=CB_CHECK_SUB)])
    return InlineKeyboardMarkup(rows)


async def _remove_reply_keyboard(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    msg = await context.bot.send_message(
        chat_id=chat_id,
        text="\u2060",
        reply_markup=ReplyKeyboardRemove(),
    )
    try:
        await msg.delete()
    except Exception:
        pass


async def send_with_banner(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    text: str,
    reply_markup: InlineKeyboardMarkup | None,
    *,
    parse_mode: str | None = None,
) -> None:
    path = _banner_path()
    if path is not None:
        with path.open("rb") as photo:
            await context.bot.send_photo(
                chat_id=chat_id,
                photo=photo,
                caption=text,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
            )
    else:
        await context.bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
            disable_web_page_preview=True,
        )


async def send_main_menu(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    await _remove_reply_keyboard(context, chat_id)
    caption = (
        "Привет! Ты в главном меню.\n"
        "Выбери раздел кнопками под этим сообщением."
    )
    await send_with_banner(
        context,
        chat_id,
        caption,
        main_menu_inline_keyboard(),
    )


async def send_promo_screen(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    await send_with_banner(
        context,
        chat_id,
        PROMO_TEXT,
        promo_reply_markup(),
        parse_mode=ParseMode.HTML,
    )


async def send_mods_list_screen(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    await send_with_banner(
        context,
        chat_id,
        MODS_LIST_TEXT,
        mods_list_keyboard(),
    )


async def send_mod_detail_screen(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    mod_id: str,
) -> None:
    if mod_id not in MODS:
        return
    n = get_mod_downloads(mod_id)
    await send_with_banner(
        context,
        chat_id,
        mod_caption_html(mod_id, n),
        mod_detail_keyboard(mod_id),
        parse_mode=ParseMode.HTML,
    )


async def send_support_screen(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    text = f"Нажми кнопку ниже — откроется чат с @{MANAGER_USERNAME}."
    await send_with_banner(
        context,
        chat_id,
        text,
        support_reply_markup(),
    )


async def _edit_mod_message_caption(
    query,
    mod_id: str,
    downloads: int,
) -> None:
    caption = mod_caption_html(mod_id, downloads)
    kb = mod_detail_keyboard(mod_id)
    try:
        if query.message.photo:
            await query.message.edit_caption(
                caption=caption,
                parse_mode=ParseMode.HTML,
                reply_markup=kb,
            )
        else:
            await query.message.edit_text(
                text=caption,
                parse_mode=ParseMode.HTML,
                reply_markup=kb,
            )
    except Exception as e:
        logger.warning("Не удалось обновить карточку мода: %s", e)


async def handle_mod_download(
    query,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Кнопка «Скачать» без URL в .env — только подсказка."""
    if not query.from_user or not query.message or not query.data:
        return
    user_id = query.from_user.id
    if not await is_user_subscribed(context, user_id):
        await query.answer("Сначала подпишись на канал.", show_alert=True)
        return

    mod_id = query.data.removeprefix("dl_")
    if mod_id not in MODS:
        await query.answer("Неизвестная модификация.", show_alert=True)
        return

    dl = (MODS[mod_id].get("download_url") or "").strip()
    if _link_usable(dl):
        await query.answer()
        return

    await query.answer(
        "Ссылка на скачивание не задана. В .env укажи MOD_*_DOWNLOAD_URL=https://... "
        "и перезапусти бота.",
        show_alert=True,
    )


async def handle_mod_count(
    query,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """+1 к счётчику после того, как пользователь скачал файл по ссылке."""
    if not query.from_user or not query.message or not query.data:
        return
    user_id = query.from_user.id
    if not await is_user_subscribed(context, user_id):
        await query.answer("Сначала подпишись на канал.", show_alert=True)
        return

    mod_id = query.data.removeprefix("cnt_")
    if mod_id not in MODS:
        await query.answer("Ошибка.", show_alert=True)
        return

    if not _link_usable((MODS[mod_id].get("download_url") or "").strip()):
        await query.answer("Сначала настрой ссылку на скачивание в .env.", show_alert=True)
        return

    count = increment_mod_downloads(mod_id)
    await _edit_mod_message_caption(query, mod_id, count)
    await query.answer("Засчитано!")


async def is_user_subscribed(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> bool:
    if not CHANNEL_ID:
        logger.warning("CHANNEL_ID не задан — подписка не проверяется.")
        return True
    try:
        member = await context.bot.get_chat_member(CHANNEL_ID, user_id)
    except Exception:
        logger.exception("get_chat_member failed")
        return False
    return member.status in (
        ChatMemberStatus.MEMBER,
        ChatMemberStatus.ADMINISTRATOR,
        ChatMemberStatus.OWNER,
    )


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    chat = update.effective_chat
    if not user or not chat:
        return

    if not await is_user_subscribed(context, user.id):
        await context.bot.send_message(
            chat_id=chat.id,
            text=(
                "Чтобы пользоваться ботом, подпишись на наш Telegram-канал.\n"
                "После подписки нажми «Проверить подписку»."
            ),
            reply_markup=not_subscribed_keyboard(),
        )
        return

    await send_main_menu(context, chat.id)


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.from_user or not query.message or not query.data:
        return

    data = query.data
    user_id = query.from_user.id
    chat_id = query.message.chat_id

    if data == CB_CHECK_SUB:
        if await is_user_subscribed(context, user_id):
            await query.answer("Готово!")
            try:
                await query.message.delete()
            except Exception:
                pass
            await context.bot.send_message(chat_id=chat_id, text="Подписка подтверждена!")
            await send_main_menu(context, chat_id)
        else:
            await query.answer(
                "Подписка не найдена. Подпишись на канал и попробуй снова.",
                show_alert=True,
            )
        return

    if data.startswith("dl_"):
        await handle_mod_download(query, context)
        return

    if data.startswith("cnt_"):
        await handle_mod_count(query, context)
        return

    if not await is_user_subscribed(context, user_id):
        await query.answer("Сначала подпишись на канал.", show_alert=True)
        return

    await query.answer()

    try:
        await query.message.delete()
    except Exception:
        pass

    if data == CB_PROMO:
        await send_promo_screen(context, chat_id)
    elif data == CB_MODS:
        await send_mods_list_screen(context, chat_id)
    elif data == CB_SUPPORT:
        await send_support_screen(context, chat_id)
    elif data == CB_MAIN:
        await send_main_menu(context, chat_id)
    elif data.startswith("mod_"):
        mid = data.removeprefix("mod_")
        if mid in MODS:
            await send_mod_detail_screen(context, chat_id, mid)


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return
    text = update.message.text.strip()
    user = update.effective_user
    chat = update.effective_chat
    if not user or not chat:
        return

    if not await is_user_subscribed(context, user.id):
        await update.message.reply_text(
            "Сначала подпишись на канал.",
            reply_markup=not_subscribed_keyboard(),
        )
        return

    if _is_promo_button(text):
        await send_promo_screen(context, chat.id)
        return

    if text == BTN_MODS:
        await send_mods_list_screen(context, chat.id)
        return

    if text == BTN_SUPPORT:
        await send_support_screen(context, chat.id)
        return


def main() -> None:
    if not BOT_TOKEN:
        hint = (
            "Не прочитан BOT_TOKEN.\n\n"
            f"1) Создайте файл (именно с таким именем): {_ENV_FILE}\n"
            "2) Скопируйте содержимое из .env.example и заполните BOT_TOKEN=...\n"
            "3) На Windows файл не должен называться .env.txt\n"
            "4) Без пробелов вокруг = в .env"
        )
        raise SystemExit(hint)

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(
        CallbackQueryHandler(
            on_callback,
            pattern=r"^(check_sub|menu_promo|menu_mods|menu_support|menu_main|mod_[a-z0-9_]+|dl_[a-z0-9_]+|cnt_[a-z0-9_]+)$",
        )
    )
    app.add_handler(MessageHandler(filters.TEXT, on_text))

    logger.info("Бот запущен")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
