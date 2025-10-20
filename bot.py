# -*- coding: utf-8 -*-
"""
TripleA Partner Feedback Bot — noSheets (RU/UZ, контакт по кнопке, больше кнопок, минимум ручного ввода)
Все ответы отправляются в Telegram‑группу (+ дубль админам).
Стек: FastAPI (webhook), Aiogram v3. Готов для Render/uvicorn.

ENV VARS
--------
BOT_TOKEN=...
WEBHOOK_URL=https://your.onrender.com/webhook
GROUP_CHAT_ID=-1001234567890
ADMINS=123456789,987654321
LOCALE=ru   # ru/uz язык по умолчанию

"""

import os
import logging
from typing import Dict, List, Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message,
    CallbackQuery,
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
)
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from datetime import datetime

# -------------------- Logging --------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("triplea.feedback")

# -------------------- ENV --------------------
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
DEFAULT_LOCALE = os.getenv("LOCALE", "ru").lower()

_GROUP = os.getenv("GROUP_CHAT_ID", "").strip()
GROUP_CHAT_ID: Optional[int] = int(_GROUP) if _GROUP and _GROUP.lstrip("-").isdigit() else None

ADMINS = [x.strip() for x in os.getenv("ADMINS", "").split(",") if x.strip()]

if not (BOT_TOKEN and WEBHOOK_URL and GROUP_CHAT_ID is not None):
    logger.warning("Missing required env vars: BOT_TOKEN / WEBHOOK_URL / GROUP_CHAT_ID")

# -------------------- i18n --------------------
T = {
    "ru": {
        "start": "Привет! Это бот для сбора обратной связи по агрегатору TripleA. Выберите язык и пройдите короткий опрос (2–3 минуты).",
        "ask_lang": "Выберите язык / Tilni tanlang:",
        "lang_switched": "Язык переключён на русский.",

        "ask_company": "1/7. Укажите название вашей компании (автопроката)",
        "ask_contact": "2/7. Нажмите кнопку, чтобы отправить ваш номер",
        "btn_share_phone": "📞 Отправить номер",

        "ask_modules": "3/7. Что тестировали? Выберите варианты:",
        "modules": [
            ("client_bot", "Клиентский Telegram‑бот"),
            ("partner_bot", "Партнёрский Telegram‑бот"),
            ("partner_web", "Веб‑кабинет партнёра"),
            ("payments", "Платежи/Инвойсы"),
            ("notifications", "Уведомления"),
            ("reports", "Отчёты/Аналитика"),
        ],

        "ask_rating": "4/7. Оцените удобство",
        "btn_rating": ["1", "2", "3", "4", "5"],

        "ask_pros": "5/7. Что понравилось? (кратко)",
        "ask_cons": "6/7. Что было непонятно/неудобно? (кратко)",
        "ask_bugs": "7/7. Нашли ошибки/баги? Опишите, пожалуйста",
        "ask_missing": "Что добавить в первую очередь? (обязательные функции)",
        "ask_ready": "Готовы продолжить тестирование после обновлений?",

        "btn_yes": "Да",
        "btn_no": "Нет",
        "btn_done": "Готово",
        "btn_next": "Далее",

        "cancel": "Опрос прерван. Можно начать снова командой /start",
        "thanks": "Спасибо! Ваш фидбек отправлен команде 👌",
        "choose": "Выберите вариант ниже:",
        "invalid_rating": "Выберите оценку кнопкой ниже",
        "help": "Команды: /start — начать, /cancel — отменить, /lang — язык, /whereami — chat_id",
    },

    "uz": {
        "start": "Salom! Bu bot TripleA agregatori bo‘yicha fikr-mulohazalarni yig‘adi. Tilni tanlang va qisqa so‘rovnomadan o‘ting (2–3 daqiqa).",
        "ask_lang": "Tilni tanlang / Выберите язык:",
        "lang_switched": "Til o‘zbek tiliga o‘zgartirildi.",

        "ask_company": "1/7. Kompaniyangiz nomi (avtoprokat)",
        "ask_contact": "2/7. Tugmani bosib telefon raqamingizni yuboring",
        "btn_share_phone": "📞 Raqamni yuborish",

        "ask_modules": "3/7. Nimalarni sinadingiz? Variantlarni tanlang:",
        "modules": [
            ("client_bot", "Mijoz Telegram boti"),
            ("partner_bot", "Hamkor Telegram boti"),
            ("partner_web", "Hamkor veb kabineti"),
            ("payments", "To‘lovlar/Hisob-faktura"),
            ("notifications", "Bildirishnomalar"),
            ("reports", "Hisobot/Analitika"),
        ],

        "ask_rating": "4/7. Qulaylikka baho bering",
        "btn_rating": ["1", "2", "3", "4", "5"],

        "ask_pros": "5/7. Nima yoqdi? (qisqa)",
        "ask_cons": "6/7. Nima tushunarsiz/noqulay bo‘ldi? (qisqa)",
        "ask_bugs": "7/7. Xatolik/bug bormi? Iltimos yozing",
        "ask_missing": "Birinchi navbatda nimani qo‘shish kerak?",
        "ask_ready": "Yangilanishlardan so‘ng davom ettirasizmi?",

        "btn_yes": "Ha",
        "btn_no": "Yo‘q",
        "btn_done": "Tayyor",
        "btn_next": "Keyingi",

        "cancel": "So‘rovnoma bekor qilindi. /start bilan qayta boshlang",
        "thanks": "Rahmat! Fikr-mulohazangiz jamoaga yuborildi 👌",
        "choose": "Quyidan tanlang:",
        "invalid_rating": "Bahoni tugma orqali tanlang",
        "help": "Buyruqlar: /start — boshlash, /cancel — bekor, /lang — til, /whereami — chat_id",
    },
}

# -------------------- Bot, DP, Router --------------------
bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()
router = Router()


def _k(locale: str, key: str) -> str:
    return T.get(locale, T[DEFAULT_LOCALE]).get(key, key)

# -------------------- FSM --------------------
class Form(StatesGroup):
    company = State()
    contact = State()
    modules = State()
    rating = State()
    pros = State()
    cons = State()
    bugs = State()
    missing = State()
    ready = State()

USER_LOCALE: Dict[int, str] = {}

# -------------------- Keyboards --------------------

def lang_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Русский", callback_data="lang:ru"),
        InlineKeyboardButton(text="O‘zbekcha", callback_data="lang:uz"),
    ]])


def contact_keyboard(locale: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=_k(locale, "btn_share_phone"), request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
        selective=True,
    )


def _grid(items: List[List[str]], columns: int = 2) -> List[List[InlineKeyboardButton]]:
    rows: List[List[InlineKeyboardButton]] = []
    row: List[InlineKeyboardButton] = []
    for code, label in items:
        row.append(InlineKeyboardButton(text=label, callback_data=code))
        if len(row) >= columns:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return rows


def modules_keyboard(locale: str, selected: Optional[List[str]] = None, columns: int = 2) -> InlineKeyboardMarkup:
    selected = selected or []
    items = []
    for code, label in T[locale]["modules"]:
        mark = " ✅" if code in selected else ""
        items.append((f"m:{code}", f"{label}{mark}"))
    rows = _grid(items, columns)
    rows.append([InlineKeyboardButton(text=_k(locale, "btn_done"), callback_data="m:done")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def rating_keyboard(locale: str) -> InlineKeyboardMarkup:
    items = [(f"r:{v}", v) for v in T[locale]["btn_rating"]]
    rows = _grid(items, columns=5)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def yesno_keyboard(locale: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=_k(locale, "btn_yes"), callback_data="yn:yes"),
        InlineKeyboardButton(text=_k(locale, "btn_no"), callback_data="yn:no"),
    ]])

# -------------------- Сервисные команды --------------------
@router.message(Command("lang"))
async def cmd_lang(m: Message):
    await m.answer(_k(USER_LOCALE.get(m.from_user.id, DEFAULT_LOCALE), "ask_lang"), reply_markup=lang_keyboard())


@router.callback_query(F.data.startswith("lang:"))
async def cb_lang(c: CallbackQuery):
    _, lang = c.data.split(":", 1)
    USER_LOCALE[c.from_user.id] = lang
    await c.message.edit_text(_k(lang, "lang_switched"))


@router.message(Command("whereami"))
async def cmd_whereami(m: Message):
    await m.answer(f"chat_id: <code>{m.chat.id}</code>\nchat_type: <code>{m.chat.type}</code>")


@router.message(CommandStart())
async def cmd_start(m: Message, state: FSMContext):
    locale = USER_LOCALE.get(m.from_user.id, DEFAULT_LOCALE)
    await state.clear()
    await m.answer(_k(locale, "ask_lang"), reply_markup=lang_keyboard())
    await m.answer(_k(locale, "start"))
    await m.answer(_k(locale, "ask_company"))
    await state.set_state(Form.company)


@router.message(Command("cancel"))
async def cmd_cancel(m: Message, state: FSMContext):
    await state.clear()
    await m.answer(_k(USER_LOCALE.get(m.from_user.id, DEFAULT_LOCALE), "cancel"))


# -------------------- Опрос --------------------
@router.message(Form.company)
async def f_company(m: Message, state: FSMContext):
    await state.update_data(company=(m.text or "").strip())
    locale = USER_LOCALE.get(m.from_user.id, DEFAULT_LOCALE)
    await m.answer(_k(locale, "ask_contact"), reply_markup=contact_keyboard(locale))
    await state.set_state(Form.contact)


@router.message(Form.contact, F.contact)
async def f_contact_button(m: Message, state: FSMContext):
    phone = m.contact.phone_number
    await state.update_data(contact=phone)
    locale = USER_LOCALE.get(m.from_user.id, DEFAULT_LOCALE)
    await m.answer("✅", reply_markup=ReplyKeyboardRemove())
    await m.answer(_k(locale, "ask_modules"), reply_markup=modules_keyboard(locale))
    await state.set_state(Form.modules)


@router.message(Form.contact)
async def f_contact_text(m: Message, state: FSMContext):
    await state.update_data(contact=(m.text or "").strip())
    locale = USER_LOCALE.get(m.from_user.id, DEFAULT_LOCALE)
    await m.answer(_k(locale, "ask_modules"), reply_markup=modules_keyboard(locale))
    await state.set_state(Form.modules)


@router.callback_query(Form.modules, F.data.startswith("m:"))
async def f_modules(c: CallbackQuery, state: FSMContext):
    locale = USER_LOCALE.get(c.from_user.id, DEFAULT_LOCALE)
    code = c.data.split(":", 1)[1]  # чистый код модуля (без префикса)
    data = await state.get_data()
    selected: List[str] = data.get("modules", [])

    if code == "done":
        if not selected:
            await c.answer(_k(locale, "choose"), show_alert=True)
            return
        await c.message.edit_reply_markup(reply_markup=None)
        await c.message.answer(_k(locale, "ask_rating"), reply_markup=rating_keyboard(locale))
        await state.set_state(Form.rating)
        return

    if code in selected:
        selected.remove(code)
    else:
        selected.append(code)

    await state.update_data(modules=selected)
    await c.message.edit_reply_markup(reply_markup=modules_keyboard(locale, selected))
    await c.answer("✓")


@router.callback_query(Form.rating, F.data.startswith("r:"))
async def f_rating_cb(c: CallbackQuery, state: FSMContext):
    val = c.data.split(":", 1)[1]
    try:
        rating = int(val)
    except Exception:
        rating = 0
    await state.update_data(rating=rating)
    locale = USER_LOCALE.get(c.from_user.id, DEFAULT_LOCALE)
    await c.message.edit_reply_markup(reply_markup=None)
    await c.message.answer(_k(locale, "ask_pros"))
    await state.set_state(Form.pros)


@router.message(Form.pros)
async def f_pros(m: Message, state: FSMContext):
    await state.update_data(pros=(m.text or "").strip())
    locale = USER_LOCALE.get(m.from_user.id, DEFAULT_LOCALE)
    await m.answer(_k(locale, "ask_cons"))
    await state.set_state(Form.cons)


@router.message(Form.cons)
async def f_cons(m: Message, state: FSMContext):
    await state.update_data(cons=(m.text or "").strip())
    locale = USER_LOCALE.get(m.from_user.id, DEFAULT_LOCALE)
    await m.answer(_k(locale, "ask_bugs"))
    await state.set_state(Form.bugs)


@router.message(Form.bugs)
async def f_bugs(m: Message, state: FSMContext):
    await state.update_data(bugs=(m.text or "").strip())
    locale = USER_LOCALE.get(m.from_user.id, DEFAULT_LOCALE)
    await m.answer(_k(locale, "ask_missing"))
    await state.set_state(Form.missing)


@router.message(Form.missing)
async def f_missing(m: Message, state: FSMContext):
    await state.update_data(missing=(m.text or "").strip())
    locale = USER_LOCALE.get(m.from_user.id, DEFAULT_LOCALE)
    await m.answer(_k(locale, "ask_ready"), reply_markup=yesno_keyboard(locale))
    await state.set_state(Form.ready)


@router.callback_query(Form.ready, F.data.startswith("yn:"))
async def f_ready(c: CallbackQuery, state: FSMContext):
    locale = USER_LOCALE.get(c.from_user.id, DEFAULT_LOCALE)
    ready_flag = c.data.endswith("yes")

    data = await state.get_data()
    user = c.from_user
    modules = data.get("modules", [])
    label_map = {code: label for code, label in T[locale]["modules"]}
    modules_labels = ", ".join(label_map.get(x, x) for x in modules)

    text = (
        "🆕 <b>Новый фидбек по MVP TripleA</b>\n"
        f"⏱ {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC\n"
        f"👤 Пользователь: <a href='tg://user?id={user.id}'>{user.full_name}</a> (@{(user.username or '').lower()})\n"
        f"🏢 Компания: {data.get('company','')}\n"
        f"📞 Контакт: {data.get('contact','')}\n"
        f"🧩 Модули: {modules_labels}\n"
        f"⭐️ Оценка: {data.get('rating','')}\n"
        f"👍 Понравилось: {data.get('pros','')}\n"
        f"👎 Неудобно: {data.get('cons','')}\n"
        f"🐞 Баги: {data.get('bugs','')}\n"
        f"➕ Must-have: {data.get('missing','')}\n"
        f"🚀 Готовы продолжать: {'Да' if ready_flag else 'Нет'}"
    )

    try:
        if GROUP_CHAT_ID is None:
            raise RuntimeError("GROUP_CHAT_ID is not set")
        await bot.send_message(GROUP_CHAT_ID, text, disable_web_page_preview=True)
    except Exception:
        logger.exception("Failed to post feedback to group")
        await c.message.answer("⚠️ Не удалось отправить в группу. Попробуйте позже.")
        await state.clear()
        return

    for admin_id in ADMINS:
        try:
            await bot.send_message(int(admin_id), text, disable_web_page_preview=True)
        except Exception:
            pass

    await c.message.edit_reply_markup(reply_markup=None)
    await c.message.answer(_k(locale, "thanks"))
    await state.clear()

# -------------------- FastAPI + Webhook --------------------
app = FastAPI(title="TripleA Partner Feedback Bot — noSheets")

@app.get("/")
async def root():
    return PlainTextResponse("ok")


@app.post("/webhook")
async def telegram_webhook(request: Request):
    data = await request.json()
    update = Update.model_validate(data)
    await dp.feed_update(bot, update)
    return JSONResponse({"ok": True})


@dp.startup()
async def on_startup():
    try:
        await bot.set_webhook(url=WEBHOOK_URL)
        logger.info("Webhook set: %s", WEBHOOK_URL)
    except Exception:
        logger.exception("Failed to set webhook")


dp.include_router(router)

# Run: uvicorn bot:app --host 0.0.0.0 --port 10000
