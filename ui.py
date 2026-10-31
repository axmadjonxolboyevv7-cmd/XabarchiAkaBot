import json
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
import db

# key: (oddiy emoji, premium/custom emoji ID). ID bo'sh bo'lsa oddiy emoji ishlatiladi.
# Premium ID olish: @getidsbot yoki emoji paketidan. Bot egasida Telegram Premium bo'lishi kerak.
EMOJI = {
 "connect": ("🔗", ""), "history": ("📜", ""), "profile": ("👤", ""), "pay": ("💎", ""), "lang": ("🌐", ""),
 "partner": ("🤝", ""), "admin": ("⚙️", ""), "check": ("✅", ""), "back": ("⬅️", ""),
 "a_stats": ("📊", ""), "a_users": ("👥", ""), "a_trial": ("⏳", ""), "a_tariffs": ("💰", ""),
 "a_tez": ("⚡", ""), "a_click": ("💳", ""), "a_channels": ("📢", ""), "a_edit": ("✏️", ""),
 "a_design": ("🎨", ""), "a_bcast": ("📣", ""), "click": ("💳", ""), "tez": ("⚡", ""),
}
DEFAULT_STYLE = {"connect": "success", "history": "primary", "profile": "primary", "pay": "success", "lang": "primary",
 "partner": "primary", "admin": "danger", "check": "success", "back": "danger", "click": "primary", "tez": "success"}
ORDER = ["primary", "success", "danger"]  # ko'k -> yashil -> qizil
ADMIN_UZ = {"a_stats": "Statistika", "a_users": "Foydalanuvchilar", "a_trial": "Bepul muddat", "a_tariffs": "Tariflar va narxlar",
 "a_tez": "Avto to'lov ulash", "a_click": "Click sozlash", "a_channels": "Majburiy kanallar",
 "a_edit": "Tugmalarni tahrirlash", "a_design": "Dizayn", "a_bcast": "Xabar yuborish", "click": "Click", "tez": "Karta (avto)"}

T = {
 "uz": {"choose_lang": "🌐 Tilni tanlang / Выберите язык / Choose language",
  "welcome": "👋 <b>Xush kelibsiz!</b>\nMen shaxsiy chatlaringizdagi <b>o'chirilgan</b> va <b>tahrirlangan</b> xabarlarni, shuningdek o'chib ketuvchi rasm/video/ovozlarni saqlayman.",
  "sub_need": "📢 Botdan foydalanish uchun quyidagi kanallarga obuna bo'ling:", "banned": "🚫 Siz cheklangansiz.",
  "profile": "👤 <b>Profil</b>\n🆔 <code>{id}</code>\n⏳ Obuna: <b>{left}</b>", "left": "{d} kun qoldi", "expired": "muddati tugagan",
  "connect": "🔗 <b>Botni ulash</b>\n1) Telegram → Sozlamalar\n2) Telegram Business → <b>Chat avtomatlashtirish</b>\n3) Bot sifatida @{u} ni tanlang va kerakli chatlarga ruxsat bering.",
  "connected": "✅ Akkaunt ulandi! Endi o'chirilgan/tahrirlangan xabarlar shu yerga yuboriladi.",
  "pay_title": "💎 <b>Obunani uzaytirish</b>\nTarifni tanlang:", "pay_none": "⚠️ To'lov tizimi hali ulanmagan.",
  "paid_ok": "✅ To'lov qabul qilindi! Obuna 30 kunga uzaytirildi.", "pick_chat": "📜 Chatni tanlang (PDF tayyorlanadi):",
  "no_chat": "Hozircha saqlangan chatlar yo'q.", "deleted": "🗑 <b>O'chirilgan xabar</b>", "edited": "✏️ <b>Tahrirlangan xabar</b>",
  "old": "Avval", "new": "Hozir", "saved_media": "💾 Saqlangan media", "expired_msg": "⛔ Obuna muddati tugagan. To'lov qiling.",
  "b_connect": "Botni ulash", "b_history": "Tarixim", "b_profile": "Profil", "b_pay": "Obuna / To'lov", "b_lang": "Til",
  "b_partner": "Hamkorlik", "b_admin": "Admin panel", "b_check": "Tekshirish", "b_back": "Orqaga"},
 "ru": {"choose_lang": "🌐 Выберите язык", "welcome": "👋 <b>Добро пожаловать!</b>\nЯ сохраняю <b>удалённые</b> и <b>изменённые</b> сообщения в личных чатах, а также исчезающие фото/видео/голосовые.",
  "sub_need": "📢 Подпишитесь на каналы:", "banned": "🚫 Вы ограничены.",
  "profile": "👤 <b>Профиль</b>\n🆔 <code>{id}</code>\n⏳ Подписка: <b>{left}</b>", "left": "осталось {d} дн.", "expired": "истекла",
  "connect": "🔗 <b>Подключение</b>\n1) Настройки Telegram\n2) Telegram Business → <b>Автоматизация чатов</b>\n3) Выберите @{u} и разрешите нужные чаты.",
  "connected": "✅ Аккаунт подключён!", "pay_title": "💎 <b>Продление</b>\nВыберите тариф:",
  "pay_none": "⚠️ Оплата не подключена.", "paid_ok": "✅ Оплата получена! Подписка продлена на 30 дней.", "pick_chat": "📜 Выберите чат (будет PDF):",
  "no_chat": "Сохранённых чатов нет.", "deleted": "🗑 <b>Удалённое сообщение</b>", "edited": "✏️ <b>Изменённое сообщение</b>",
  "old": "Было", "new": "Стало", "saved_media": "💾 Сохранённое медиа", "expired_msg": "⛔ Подписка истекла. Оплатите.",
  "b_connect": "Подключить бота", "b_history": "Моя история", "b_profile": "Профиль", "b_pay": "Подписка / Оплата", "b_lang": "Язык",
  "b_partner": "Партнёрство", "b_admin": "Админ-панель", "b_check": "Проверить", "b_back": "Назад"},
 "en": {"choose_lang": "🌐 Choose language", "welcome": "👋 <b>Welcome!</b>\nI save <b>deleted</b> and <b>edited</b> messages from your private chats, plus self-destructing photos/videos/voice.",
  "sub_need": "📢 Please subscribe to these channels:", "banned": "🚫 You are restricted.",
  "profile": "👤 <b>Profile</b>\n🆔 <code>{id}</code>\n⏳ Subscription: <b>{left}</b>", "left": "{d} days left", "expired": "expired",
  "connect": "🔗 <b>Connect</b>\n1) Telegram Settings\n2) Telegram Business → <b>Chatbots</b>\n3) Pick @{u} and allow the chats.",
  "connected": "✅ Account connected!", "pay_title": "💎 <b>Extend subscription</b>\nChoose a plan:",
  "pay_none": "⚠️ Payments not configured.", "paid_ok": "✅ Payment received! Extended by 30 days.", "pick_chat": "📜 Pick a chat (PDF will be sent):",
  "no_chat": "No saved chats yet.", "deleted": "🗑 <b>Deleted message</b>", "edited": "✏️ <b>Edited message</b>",
  "old": "Before", "new": "Now", "saved_media": "💾 Saved media", "expired_msg": "⛔ Subscription expired. Please pay.",
  "b_connect": "Connect bot", "b_history": "My history", "b_profile": "Profile", "b_pay": "Subscription / Pay", "b_lang": "Language",
  "b_partner": "Partnership", "b_admin": "Admin panel", "b_check": "Check", "b_back": "Back"},
}

async def get_ui(bid):
    return {"labels": json.loads(await db.get(bid, "labels", "{}")), "styles": json.loads(await db.get(bid, "styles", "{}"))}

def label_of(ui, key, lang="uz"):
    return ui["labels"].get(key) or T[lang].get("b_" + key) or ADMIN_UZ.get(key) or key

def btn(ui, key, lang="uz", **kw):
    uni, cid = EMOJI.get(key, ("", ""))
    label = label_of(ui, key, lang)
    style = ui["styles"].get(key) or DEFAULT_STYLE.get(key, "primary")
    extra = {"style": style}
    if cid:
        extra["icon_custom_emoji_id"] = cid; text = label
    else:
        text = f"{uni} {label}".strip()
    return InlineKeyboardButton(text=text, **extra, **kw)

def kb(rows): return InlineKeyboardMarkup(inline_keyboard=rows)
def raw(text, style="primary", **kw): return InlineKeyboardButton(text=text, style=style, **kw)

def btn_text(ui, key, lang="uz"):
    uni, cid = EMOJI.get(key, ("", ""))
    label = label_of(ui, key, lang)
    return label if cid else f"{uni} {label}".strip()

def rbtn(ui, key, lang="uz"):
    uni, cid = EMOJI.get(key, ("", ""))
    extra = {"style": ui["styles"].get(key) or DEFAULT_STYLE.get(key, "primary")}
    if cid: extra["icon_custom_emoji_id"] = cid
    return KeyboardButton(text=btn_text(ui, key, lang), **extra)

def rkb(rows): return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True, is_persistent=True)

USER_KEYS = ["connect", "history", "profile", "pay", "lang", "partner", "admin"]
ADMIN_KEYS = ["a_stats", "a_users", "a_trial", "a_tariffs", "a_tez", "a_click", "a_channels", "a_edit", "a_design", "a_bcast", "back"]
