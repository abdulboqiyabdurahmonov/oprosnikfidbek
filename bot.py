# -*- coding: utf-8 -*-
"""
TripleA Partner Feedback Bot — версия БЕЗ Google Sheets.
Все ответы отправляются в Telegram‑группу (и/или админам в ЛС).
Стек: FastAPI (webhook), Aiogram v3. Render‑ready.

ENV VARS
--------
BOT_TOKEN=...                          # токен бота
WEBHOOK_URL=https://your.onrender.com/webhook
WEBHOOK_SECRET=supersecret             # секрет для заголовка x-telegram-bot-api-secret-token
GROUP_CHAT_ID=-1001234567890           # ID вашей TG‑группы (отрицательное число)
ADMINS=123456789,987654321             # кому дублировать фидбек в ЛС (опц.)
LOCALE=ru                              # ru/uz — язык по умолчанию

Как узнать GROUP_CHAT_ID быстро:
1) Добавьте бота в нужную группу и сделайте его админом (право «Отправлять сообщения» достаточно).
2) В группе напишите команду /whereami — бот ответит chat_id.

"""

import os
import logging
from typing import Dict, Any, List, Optional

from fastapi import FastAPI, Request, Header, HTTPException
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
)
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from datetime import datetime

# -------------------- Logging --------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("triplea.feedback")

# -------------------- ENV --------------------
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
DEFAULT_LOCALE = os.getenv("LOCALE", "ru").lower()

# GROUP_CHAT_ID должен быть int (обычно отрицательный для супергрупп)
_GROUP = os.getenv("GROUP_CHAT_ID", "").strip()
GROUP_CHAT_ID: Optional[int] = int(_GROUP) if _GROUP and _GROUP.lstrip("-").isdigit() else None

ADMINS = [x.strip() for x in os.getenv("ADMINS", "").split(",") if x.strip()]

if not (BOT_TOKEN and WEBHOOK_URL and GROUP_CHAT_ID is not None):
    logger.warning("Missing required env vars: BOT_TOKEN / WEBHOOK_URL / GROUP_CHAT_ID")

# -------------------- i18n --------------------
T = {
    "ru": {
        "start": "Привет! Это бот для сбора обратной связи по агрегатору TripleA. Давайте пройдём короткий опрос (2–3 минуты).",
        "ask_company": "1/7. Укажите название вашей компании (автопроката)",
        "ask_contact": "2/7. Как с вами связаться? Оставьте телефон или @username",
        "ask_modules": "3/7. Что тестировали? Выберите все подходящие варианты:",
        "modules": [
            ("client_bot", "Клиентский Telegram‑бот"),
            ("partner_bot", "Партнёрский Telegram‑бот"),
            ("partner_web", "Веб‑кабинет партнёра"),
        ],
        "ask_rating": "4/7. Общая оценка удобства по шкале 1–5 (1 — неудобно, 5 — супер)",
        "ask_pros": "5/7. Что понравилось? (кратко)",
        "ask_cons": "6/7. Что было непонятно/неудобно? (кратко)",
        "ask_bugs": "7/7. Нашли ошибки/баги? Опишите, пожалуйста",
        "ask_missing": "Что добавить в первую очередь? (обязательные функции)",
        "ask_ready": "Готовы продолжить тестирование после обновлений?",
        "btn_yes": "Да",
        "btn_no": "Нет",
        "btn_done": "Готово",
        "cancel": "Опрос прерван. Можно начать снова командой /start",
        "thanks": "Спасибо! Ваш фидбек отправлен команде 👌",
        "invalid_rating": "Пожалуйста, введите число от 1 до 5",
        "choose": "Выберите вариант ниже:",
        "lang_switched": "Язык переключён на русский.",
        "help": "Команды: /start — начать опрос, /cancel — отменить, /lang — выбрать язык, /whereami — показать chat_id",
        "ask_lang": "Выберите язык / Tilni tanlang:",
    },
    "uz": {
        "start": "Salom! Bu bot TripleA agregatori bo‘yicha fikr-mulohazalarni yig‘ish uchun. Keling, qisqa so‘rovnomadan o‘tamiz (2–3 daqiqa).",
        "ask_company": "1/7. Kompaniyangiz (avtoprokat) nomini kiriting",
        "ask_contact": "2/7. Qanday bog‘lansak bo‘ladi? Telefon yoki @username qoldiring",
        "ask_modules": "3/7. Nimani sinadingiz? Mos variantlarni tanlang:",
        "modules": [
            ("client_bot", "Mijoz Telegram boti"),
            ("partner_bot", "Hamkor Telegram boti"),
            ("partner_web", "Hamkorning veb kabineti"),
        ],
        "ask_rating": "4/7. Qulaylik bo‘yicha umumiy baho 1–5 (1 — noqulay, 5 — juda yaxshi)",
        "ask_pros": "5/7. Nima yoqdi? (qisqa)",
        "ask_cons": "6/7. Nima tushunarsiz/noqulay bo‘ldi? (qisqa)",
        "ask_bugs": "7/7. Xatolik/bug topildimi? Iltimos, yozib bering",
        "ask_missing": "Birinchi navbatda nimani qo‘shish kerak? (majburiy funksiyalar)",
        "ask_ready": "Yangilanishlardan so‘ng testni davom ettirasizmi?",
        "btn_yes": "Ha",
        "btn_no": "Yo‘q",
        "btn_done": "Tayyor",
        "cancel": "So‘rovnoma bekor qilindi. /start bilan qaytadan boshlashingiz mumkin",
        "thanks": "Rahmat! Fikr-mulohazangiz jamoaga yuborildi 👌",
        "invalid_rating": "Iltimos, 1 dan 5 gacha bo‘lgan son kiriting",
        "choose": "Quyidagi variantlardan tanlang:",
        "lang_switched": "Til o‘zbek tiliga o‘zgartirildi.",
        "help": "Buyruqlar: /start — boshlash, /cancel — bekor qilish, /lang — tilni tanlash, /whereami — chat_id",
        "ask_lang": "Tilni tanlang / Выберите язык:",
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

# user locale in memory (для MVP)
USER_LOCALE: Dict[int, str] = {}

# -------------------- Keyboards --------------------

def lang_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Русский", callback_data="lang:ru"),
        InlineKeyboardButton(text="O‘zbekcha", callback_data="lang:uz")
    ]])


def modules_keyboard(locale: str, selected: Optional[List[str]] = None) -> InlineKeyboardMarkup:
    selected = selected or []
    rows = []
    for code, label in T[locale]["modules"]:
        mark = " ✅" if code in selected else ""
        rows.append([InlineKeyboardButton(text=f"{label}{mark}", callback_data=f"m:{code}")])
    rows.append([InlineKeyboardButton(text=_k(locale, "btn_done"), callback_data="m:done")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def yesno_keyboard(locale: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=_k(locale, "btn_yes"), callback_data="yn:yes"),
        InlineKeyboardButton(text=_k(locale, "btn_no"), callback_data="yn:no"),
    ]])

# -------------------- Service commands --------------------
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
    await m.answer(f"chat_id: <code>{m.chat.id}</code>
chat_type: <code>{m.chat.type}</code>")


@router.message(CommandStart())
async def cmd_start(m: Message, state: FSMContext):
    locale = USER_LOCALE.get(m.from_user.id, DEFAULT_LOCALE)
    await state.clear()
    await m.answer(_k(locale, "start"))
    await m.answer(_k(locale, "ask_company"))
    await state.set_state(Form.company)


@router.message(Command("cancel"))
async def cmd_cancel(m: Message, state: FSMContext):
    await state.clear()
    await m.answer(_k(USER_LOCALE.get(m.from_user.id, DEFAULT_LOCALE), "cancel"))


# -------------------- Flow --------------------
@router.message(Form.company)
async def f_company(m: Message, state: FSMContext):
    await state.update_data(company=m.text.strip())
    locale = USER_LOCALE.get(m.from_user.id, DEFAULT_LOCALE)
    await m.answer(_k(locale, "ask_contact"))
    await state.set_state(Form.contact)


@router.message(Form.contact)
async def f_contact(m: Message, state: FSMContext):
    await state.update_data(contact=m.text.strip(), modules=[])
    locale = USER_LOCALE.get(m.from_user.id, DEFAULT_LOCALE)
    await m.answer(_k(locale, "ask_modules"), reply_markup=modules_keyboard(locale))
    await state.set_state(Form.modules)


@router.callback_query(Form.modules, F.data.startswith("m:"))
async def f_modules(c: CallbackQuery, state: FSMContext):
    locale = USER_LOCALE.get(c.from_user.id, DEFAULT_LOCALE)
    code = c.data.split(":", 1)[1]
    data = await state.get_data()
    selected: List[str] = data.get("modules", [])

    if code == "done":
        if not selected:
            await c.answer(_k(locale, "choose"), show_alert=True)
            return
        await c.message.edit_reply_markup(reply_markup=None)
        await c.message.answer(_k(locale, "ask_rating"))
        await state.set_state(Form.rating)
        return

    if code in selected:
        selected.remove(code)
    else:
        selected.append(code)

    await state.update_data(modules=selected)
    await c.message.edit_reply_markup(reply_markup=modules_keyboard(locale, selected))
    await c.answer("✓")


@router.message(Form.rating)
async def f_rating(m: Message, state: FSMContext):
    locale = USER_LOCALE.get(m.from_user.id, DEFAULT_LOCALE)
    try:
        val = int(m.text.strip())
        if val < 1 or val > 5:
            raise ValueError
    except Exception:
        await m.answer(_k(locale, "invalid_rating"))
        return
    await state.update_data(rating=val)
    await m.answer(_k(locale, "ask_pros"))
    await state.set_state(Form.pros)


@router.message(Form.pros)
async def f_pros(m: Message, state: FSMContext):
    await state.update_data(pros=m.text.strip())
    locale = USER_LOCALE.get(m.from_user.id, DEFAULT_LOCALE)
    await m.answer(_k(locale, "ask_cons"))
    await state.set_state(Form.cons)


@router.message(Form.cons)
async def f_cons(m: Message, state: FSMContext):
    await state.update_data(cons=m.text.strip())
    locale = USER_LOCALE.get(m.from_user.id, DEFAULT_LOCALE)
    await m.answer(_k(locale, "ask_bugs"))
    await state.set_state(Form.bugs)


@router.message(Form.bugs)
async def f_bugs(m: Message, state: FSMContext):
    await state.update_data(bugs=m.text.strip())
    locale = USER_LOCALE.get(m.from_user.id, DEFAULT_LOCALE)
    await m.answer(_k(locale, "ask_missing"))
    await state.set_state(Form.missing)


@router.message(Form.missing)
async def f_missing(m: Message, state: FSMContext):
    await state.update_data(missing=m.text.strip())
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

    # Сформируем текст отчёта
    lines = [
        "🆕 <b>Новый фидбек по MVP TripleA</b>",
        f"⏱ {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC",
        f"👤 Пользователь: <a href='tg://user?id={user.id}'>{user.full_name}</a> (@{(user.username or '').lower()})",
        f"🏢 Компания: {data.get('company','')}",
        f"📞 Контакт: {data.get('contact','')}",
        f"🧩 Модули: {modules_labels}",
        f"⭐️ Оценка: {data.get('rating','')}",
        f"👍 Понравилось: {data.get('pros','')}",
        f"👎 Неудобно: {data.get('cons','')}",
        f"🐞 Баги: {data.get('bugs','')}",
        f"➕ Must‑have: {data.get('missing','')}",
        f"🚀 Готовы продолжать: {'Да' if ready_flag else 'Нет'}",
    ]

    text = "
".join(lines)

    # Отправка в группу
    try:
        if GROUP_CHAT_ID is None:
            raise RuntimeError("GROUP_CHAT_ID is not set")
        await bot.send_message(GROUP_CHAT_ID, text, disable_web_page_preview=True)
    except Exception:
        logger.exception("Failed to post feedback to group")
        await c.message.answer("⚠️ Не удалось отправить в группу. Попробуйте позже.")
        await state.clear()
        return

    # Дублируем админам (если указаны)
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
async def telegram_webhook(request: Request, x_telegram_bot_api_secret_token: Optional[str] = Header(None)):
    if WEBHOOK_SECRET:
        if x_telegram_bot_api_secret_token != WEBHOOK_SECRET:
            raise HTTPException(status_code=403, detail="Invalid secret token")
    data = await request.json()
    update = Update.model_validate(data)
    await dp.feed_update(bot, update)
    return JSONResponse({"ok": True})


@dp.startup()
async def on_startup():
    try:
        await bot.set_webhook(url=WEBHOOK_URL, secret_token=WEBHOOK_SECRET)
        logger.info("Webhook set: %s", WEBHOOK_URL)
    except Exception:
        logger.exception("Failed to set webhook")


dp.include_router(router)

# Run: uvicorn bot:app --host 0.0.0.0 --port 10000
