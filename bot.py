import json, os, random, time
from html import escape
from aiogram import Router, F, Bot
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (Message, CallbackQuery, BusinessConnection, BusinessMessagesDeleted,
                           FSInputFile, LabeledPrice, PreCheckoutQuery)
from aiogram.exceptions import TelegramBadRequest
import db
from config import ADMIN_IDS, TRIAL_DAYS, DEFAULT_PRICE, MEDIA_DIR
from ui import T, EMOJI, ORDER, ADMIN_UZ, get_ui, btn, kb, raw, label_of
from payments import tez_create, tez_check
from pdfgen import make_pdf

class S(StatesGroup):
    tez_acc = State(); tez_kassa = State(); click = State(); price = State(); trial = State()
    chan = State(); uid = State(); udays = State(); rename = State(); bcast = State(); token = State()

# ---------- yordamchilar ----------
async def is_main(bid): return bool((await db.one("SELECT is_main FROM bots WHERE bot_id=?", bid) or {"is_main": 0})["is_main"])
async def is_admin(bid, uid):
    b = await db.one("SELECT owner_id,is_main FROM bots WHERE bot_id=?", bid)
    if not b: return False
    return uid in ADMIN_IDS if b["is_main"] else uid == b["owner_id"]   # klon admin paneli faqat klon egasiga

async def ensure_user(bid, u):
    row = await db.one("SELECT * FROM users WHERE bot_id=? AND user_id=?", bid, u.id)
    if row: return row
    days = int(await db.get(bid, "trial_days", TRIAL_DAYS)); now = int(time.time())
    await db.ex("INSERT INTO users VALUES(?,?,?,?,?,?,0)", bid, u.id, None, u.full_name, now, now + days * 86400)
    return await db.one("SELECT * FROM users WHERE bot_id=? AND user_id=?", bid, u.id)

async def extend(bid, uid, days):
    u = await db.one("SELECT expires FROM users WHERE bot_id=? AND user_id=?", bid, uid)
    base = max(int(time.time()), u["expires"] if u else 0)
    await db.ex("UPDATE users SET expires=? WHERE bot_id=? AND user_id=?", base + days * 86400, bid, uid)

async def allowed(bid, uid):
    if await is_admin(bid, uid): return True
    u = await db.one("SELECT * FROM users WHERE bot_id=? AND user_id=?", bid, uid)
    return bool(u and not u["banned"] and u["expires"] > time.time())

async def lang_of(bid, uid):
    u = await db.one("SELECT lang FROM users WHERE bot_id=? AND user_id=?", bid, uid)
    return (u and u["lang"]) or "uz"

async def not_subscribed(bot, bid, uid):
    bad = []
    for c in json.loads(await db.get(bid, "channels", "[]")):
        try:
            m = await bot.get_chat_member(c, uid)
            if m.status in ("left", "kicked"): bad.append(c)
        except Exception: pass
    return bad

def lang_kb():
    return kb([[raw("🇺🇿 O'zbekcha", "success", callback_data="l:uz")], [raw("🇷🇺 Русский", "primary", callback_data="l:ru")],
               [raw("🇬🇧 English", "danger", callback_data="l:en")]])

async def send_menu(bot, bid, uid):
    lang = await lang_of(bid, uid); ui = await get_ui(bid)
    bad = await not_subscribed(bot, bid, uid)
    if bad:
        rows = [[raw(f"📢 {c}", "primary", url=f"https://t.me/{c.lstrip('@')}")] for c in bad] + [[btn(ui, "check", lang, callback_data="m:check")]]
        return await bot.send_message(uid, T[lang]["sub_need"], reply_markup=kb(rows))
    rows = [[btn(ui, "connect", lang, callback_data="m:connect")],
            [btn(ui, "history", lang, callback_data="m:history"), btn(ui, "profile", lang, callback_data="m:profile")],
            [btn(ui, "pay", lang, callback_data="m:pay"), btn(ui, "lang", lang, callback_data="m:lang")]]
    if await is_main(bid): rows.append([btn(ui, "partner", lang, callback_data="m:partner")])
    if await is_admin(bid, uid): rows.append([btn(ui, "admin", lang, callback_data="m:admin")])
    await bot.send_message(uid, T[lang]["welcome"], reply_markup=kb(rows))

def extract(m):
    if m.photo: return "photo", m.photo[-1].file_id, "jpg"
    if m.video: return "video", m.video.file_id, "mp4"
    if m.video_note: return "video_note", m.video_note.file_id, "mp4"
    if m.voice: return "voice", m.voice.file_id, "ogg"
    if m.audio: return "audio", m.audio.file_id, "mp3"
    if m.animation: return "animation", m.animation.file_id, "mp4"
    if m.document: return "document", m.document.file_id, "bin"
    return "text", None, None

async def dl(bot, bid, msg, fid, ext):
    path = os.path.join(MEDIA_DIR, f"{bid}_{msg.chat.id}_{msg.message_id}.{ext}")
    if not os.path.exists(path):
        try: await bot.download(fid, destination=path)
        except Exception: return None
    return path

async def send_media(bot, chat_id, typ, path, caption=""):
    f = FSInputFile(path); cap = caption[:1000]
    fn = {"photo": bot.send_photo, "video": bot.send_video, "voice": bot.send_voice, "audio": bot.send_audio,
          "animation": bot.send_animation, "document": bot.send_document}.get(typ)
    if typ == "video_note":
        await bot.send_video_note(chat_id, f); 
        if cap: await bot.send_message(chat_id, cap)
    elif fn:
        key = {"photo": "photo", "video": "video", "voice": "voice", "audio": "audio", "animation": "animation", "document": "document"}[typ]
        await fn(chat_id, **{key: f}, caption=cap)

async def conn_owner(bot, bid, conn_id):
    r = await db.one("SELECT user_id FROM conns WHERE bot_id=? AND conn_id=?", bid, conn_id)
    if r: return r["user_id"]
    try:
        c = await bot.get_business_connection(conn_id)
        await db.ex("INSERT OR REPLACE INTO conns VALUES(?,?,?)", bid, conn_id, c.user.id); return c.user.id
    except Exception: return None

async def save_msg(bid, conn, m, typ, path):
    await db.ex("INSERT OR IGNORE INTO msgs VALUES(?,?,?,?,?,?,?,?,?,?,?,'ok')", bid, conn, m.chat.id, m.message_id, m.chat.full_name,
                m.from_user.id if m.from_user else 0, m.from_user.full_name if m.from_user else "?", typ, m.text or m.caption or "", path, int(time.time()))

# ---------- router ----------
def build_router():
    r = Router()

    # --- start / til ---
    @r.message(CommandStart())
    async def start(m: Message, state: FSMContext):
        await state.clear(); bid = m.bot.id
        u = await ensure_user(bid, m.from_user)
        if u["banned"]: return await m.answer(T["uz"]["banned"])
        if not u["lang"]: return await m.answer(T["uz"]["choose_lang"], reply_markup=lang_kb())
        await send_menu(m.bot, bid, m.from_user.id)

    @r.callback_query(F.data.startswith("l:"))
    async def setlang(c: CallbackQuery):
        await ensure_user(c.bot.id, c.from_user)
        await db.ex("UPDATE users SET lang=? WHERE bot_id=? AND user_id=?", c.data[2:], c.bot.id, c.from_user.id)
        await c.answer("✅"); await c.message.delete(); await send_menu(c.bot, c.bot.id, c.from_user.id)

    # --- asosiy menyu ---
    @r.callback_query(F.data.startswith("m:"))
    async def menu(c: CallbackQuery, state: FSMContext):
        bot, bid, uid = c.bot, c.bot.id, c.from_user.id
        u = await ensure_user(bid, c.from_user)
        if u["banned"]: return await c.answer(T["uz"]["banned"], show_alert=True)
        lang = u["lang"] or "uz"; ui = await get_ui(bid); k = c.data[2:]; await c.answer()
        back = [btn(ui, "back", lang, callback_data="m:home")]
        if k in ("home", "check"):
            await c.message.delete(); return await send_menu(bot, bid, uid)
        if k == "lang": return await c.message.answer(T["uz"]["choose_lang"], reply_markup=lang_kb())
        if k == "connect":
            me = await bot.me(); txt = T[lang]["connect"].format(u=me.username)
            try: return await c.message.answer(txt, reply_markup=kb([[btn(ui, "connect", lang, url="tg://settings")], back]))
            except TelegramBadRequest: return await c.message.answer(txt, reply_markup=kb([back]))
        if k == "profile":
            d = (u["expires"] - time.time()) / 86400
            left = T[lang]["left"].format(d=int(d) + 1) if d > 0 else T[lang]["expired"]
            return await c.message.answer(T[lang]["profile"].format(id=uid, left=left), reply_markup=kb([back]))
        if k == "pay":
            price = int(await db.get(bid, "price", DEFAULT_PRICE)); rows = []
            if await db.get(bid, "click_token"): rows.append([btn(ui, "click", lang, callback_data="p:click")])
            if await db.get(bid, "tez_on"): rows.append([btn(ui, "tez", lang, callback_data="p:tez")])
            if not rows: return await c.message.answer(T[lang]["pay_none"], reply_markup=kb([back]))
            return await c.message.answer(T[lang]["pay_title"].format(p=price), reply_markup=kb(rows + [back]))
        if k == "history":
            rows = await db.all_("""SELECT chat_id, MAX(chat_name) n, COUNT(*) c FROM msgs WHERE bot_id=? AND conn_id IN
                (SELECT conn_id FROM conns WHERE bot_id=? AND user_id=?) GROUP BY chat_id ORDER BY MAX(date) DESC LIMIT 20""", bid, bid, uid)
            if not rows: return await c.message.answer(T[lang]["no_chat"], reply_markup=kb([back]))
            btns = [[raw(f"💬 {x['n']} ({x['c']})", "primary", callback_data=f"h:{x['chat_id']}")] for x in rows]
            return await c.message.answer(T[lang]["pick_chat"], reply_markup=kb(btns + [back]))
        if k == "partner" and await is_main(bid):
            await state.set_state(S.token)
            return await c.message.answer("🤝 <b>Hamkorlik</b>\n@BotFather da bot yarating va uning <b>tokenini</b> yuboring.\nSiz o'z botingizni to'liq boshqarasiz (o'z admin panelingiz bilan).", reply_markup=kb([back]))
        if k == "admin" and await is_admin(bid, uid): return await admin_home(c.message, bid, ui)

    @r.callback_query(F.data.startswith("h:"))
    async def hist(c: CallbackQuery):
        bid, uid, chat = c.bot.id, c.from_user.id, int(c.data[2:]); await c.answer("⏳ PDF...")
        rows = await db.all_("""SELECT * FROM msgs WHERE bot_id=? AND chat_id=? AND conn_id IN (SELECT conn_id FROM conns WHERE bot_id=? AND user_id=?)
            ORDER BY date""", bid, chat, bid, uid)
        if not rows: return
        path = os.path.join(MEDIA_DIR, f"hist_{bid}_{uid}_{chat}.pdf")
        make_pdf(path, f"Chat tarixi: {rows[0]['chat_name']}", rows)
        await c.message.answer_document(FSInputFile(path, filename=f"tarix_{chat}.pdf")); os.remove(path)

    # --- to'lovlar ---
    @r.callback_query(F.data == "p:click")
    async def p_click(c: CallbackQuery):
        bid = c.bot.id; tok = await db.get(bid, "click_token"); price = int(await db.get(bid, "price", DEFAULT_PRICE)); await c.answer()
        await c.bot.send_invoice(c.from_user.id, "Obuna 30 kun", "Xabarlarni saqlash xizmati", f"sub:{bid}:{c.from_user.id}", tok, "UZS",
                                 [LabeledPrice(label="30 kun", amount=price * 100)])

    @r.pre_checkout_query()
    async def pre(q: PreCheckoutQuery): await q.answer(ok=True)

    @r.message(F.successful_payment)
    async def paid(m: Message):
        bid, uid = m.bot.id, m.from_user.id; sp = m.successful_payment
        await extend(bid, uid, 30)
        await db.ex("INSERT INTO pays(bot_id,user_id,method,amount,status,ref,ts) VALUES(?,?,?,?,?,?,?)", bid, uid, "click", sp.total_amount // 100, "paid", sp.provider_payment_charge_id, int(time.time()))
        await m.answer(T[await lang_of(bid, uid)]["paid_ok"])

    @r.callback_query(F.data == "p:tez")
    async def p_tez(c: CallbackQuery):
        bid, uid = c.bot.id, c.from_user.id; await c.answer(); lang = await lang_of(bid, uid); ui = await get_ui(bid)
        price = int(await db.get(bid, "price", DEFAULT_PRICE)); amount = price + random.randint(1, 99)
        cur = await db.ex("INSERT INTO pays(bot_id,user_id,method,amount,status,ref,ts) VALUES(?,?,?,?,?,?,?)", bid, uid, "tez", amount, "pending", "", int(time.time()))
        pid = cur.lastrowid; ref = f"TZ{bid}_{pid}"; await db.ex("UPDATE pays SET ref=? WHERE id=?", ref, pid)
        d = await tez_create(await db.get(bid, "tez_acc"), await db.get(bid, "tez_kassa"), amount, ref)
        info = d.get("url") or d.get("card") or d.get("pay_url") or ""
        await c.message.answer(f"⚡ <b>Avto to'lov</b>\n💰 Aynan <b>{amount}</b> so'm to'lang.\n{escape(str(info))}\n\nTo'lov avtomatik aniqlanadi.",
                               reply_markup=kb([[btn(ui, "check", lang, callback_data=f"p:chk:{pid}")]]))

    @r.callback_query(F.data.startswith("p:chk:"))
    async def p_chk(c: CallbackQuery):
        bid = c.bot.id; p = await db.one("SELECT * FROM pays WHERE id=? AND bot_id=?", int(c.data[6:]), bid)
        if not p: return await c.answer()
        if p["status"] == "paid": return await c.answer("✅", show_alert=True)
        if await tez_check(await db.get(bid, "tez_acc"), await db.get(bid, "tez_kassa"), p["ref"]):
            await db.ex("UPDATE pays SET status='paid' WHERE id=?", p["id"]); await extend(bid, p["user_id"], 30)
            await c.message.answer(T[await lang_of(bid, p["user_id"])]["paid_ok"])
        else: await c.answer("⏳ To'lov hali topilmadi", show_alert=True)

    # --- hamkorlik: klon bot yaratish ---
    @r.message(S.token, F.text)
    async def new_clone(m: Message, state: FSMContext):
        from manager import start_clone
        try:
            b = Bot(m.text.strip()); me = await b.get_me(); await b.session.close()
        except Exception: return await m.answer("❌ Token noto'g'ri. Qayta yuboring.")
        if await db.one("SELECT 1 FROM bots WHERE bot_id=?", me.id): return await m.answer("❌ Bu bot allaqachon ulangan.")
        await db.ex("INSERT INTO bots VALUES(?,?,?,?,0)", me.id, m.text.strip(), me.username, m.from_user.id)
        await start_clone(m.text.strip()); await state.clear()
        await m.answer(f"✅ @{me.username} tayyor!\nUni boshqarish uchun botingizga kirib /start bosing — u yerda <b>Admin panel</b> paydo bo'ladi.")

    # --- admin panel (har bir bot egasi uchun alohida) ---
    async def admin_home(msg, bid, ui):
        rows = [[btn(ui, "a_stats", callback_data="a:stats"), btn(ui, "a_users", callback_data="a:users")],
                [btn(ui, "a_trial", callback_data="a:trial"), btn(ui, "a_price", callback_data="a:price")],
                [btn(ui, "a_tez", callback_data="a:tez")], [btn(ui, "a_click", callback_data="a:click")],
                [btn(ui, "a_channels", callback_data="a:chan")],
                [btn(ui, "a_edit", callback_data="a:edit"), btn(ui, "a_design", callback_data="a:design")],
                [btn(ui, "a_bcast", callback_data="a:bcast")], [btn(ui, "back", callback_data="m:home")]]
        await msg.answer("⚙️ <b>Admin panel</b>", reply_markup=kb(rows))

    @r.callback_query(F.data.startswith("a:"))
    async def admin(c: CallbackQuery, state: FSMContext):
        bid = c.bot.id
        if not await is_admin(bid, c.from_user.id): return await c.answer("⛔", show_alert=True)
        k = c.data[2:]; ui = await get_ui(bid); await c.answer(); back = [btn(ui, "back", callback_data="m:admin")]
        asks = {"tez": (S.tez_acc, "⚡ <b>tezcheck.uz</b>\n🔑 <b>Hisob API</b> ni kiriting:"), "click": (S.click, "💳 BotFather → Payments → Click <b>provider token</b>ni yuboring:"),
                "price": (S.price, "💰 Yangi narxni kiriting (so'm / 30 kun):"), "trial": (S.trial, "⏳ Yangi foydalanuvchilar uchun bepul kun sonini kiriting:"),
                "users": (S.uid, "👥 Foydalanuvchi ID raqamini kiriting:"), "bcast": (S.bcast, "📣 Barcha foydalanuvchilarga yuboriladigan matnni kiriting:")}
        if k in asks:
            await state.set_state(asks[k][0]); return await c.message.answer(asks[k][1], reply_markup=kb([back]))
        if k == "stats":
            now = int(time.time())
            g = lambda s, *a: db.one(s, bid, *a)
            tot = (await g("SELECT COUNT(*) n FROM users WHERE bot_id=?"))["n"]
            act = (await g("SELECT COUNT(*) n FROM users WHERE bot_id=? AND expires>? AND banned=0", now))["n"]
            ban = (await g("SELECT COUNT(*) n FROM users WHERE bot_id=? AND banned=1"))["n"]
            new = (await g("SELECT COUNT(*) n FROM users WHERE bot_id=? AND joined>?", now - 86400))["n"]
            msgs = (await g("SELECT COUNT(*) n FROM msgs WHERE bot_id=?"))["n"]
            dels = (await g("SELECT COUNT(*) n FROM msgs WHERE bot_id=? AND status='deleted'"))["n"]
            inc = (await g("SELECT COALESCE(SUM(amount),0) n FROM pays WHERE bot_id=? AND status='paid'"))["n"]
            return await c.message.answer(f"📊 <b>Statistika</b>\n👥 Jami: <b>{tot}</b>\n✅ Faol: <b>{act}</b>\n🚫 Cheklangan: <b>{ban}</b>\n🆕 24 soatda: <b>{new}</b>\n💬 Saqlangan xabar: <b>{msgs}</b>\n🗑 O'chirilgan: <b>{dels}</b>\n💰 Tushum: <b>{inc}</b> so'm", reply_markup=kb([back]))
        if k == "chan":
            ch = json.loads(await db.get(bid, "channels", "[]"))
            rows = [[raw(f"❌ {x}", "danger", callback_data=f"ch:del:{x}")] for x in ch] + [[raw("➕ Kanal qo'shish", "success", callback_data="ch:add")], back]
            return await c.message.answer("📢 <b>Majburiy kanallar</b>\nBotni kanalga admin qiling.", reply_markup=kb(rows))
        if k == "edit":
            rows = [[btn(ui, key, callback_data=f"e:{key}")] for key in EMOJI if key not in ("tez", "click")]
            return await c.message.answer("✏️ Tahrirlash uchun tugmani bosing:", reply_markup=kb(rows + [back]))
        if k == "design": return await c.message.answer("🎨 Rangini almashtirish uchun tugmani bosing (🔵→🟢→🔴):", reply_markup=await design_kb(bid, ui, back))

    async def design_kb(bid, ui, back):
        return kb([[btn(ui, key, callback_data=f"d:{key}")] for key in EMOJI] + [back])

    @r.callback_query(F.data.startswith("d:"))
    async def design(c: CallbackQuery):
        bid = c.bot.id
        if not await is_admin(bid, c.from_user.id): return await c.answer()
        key = c.data[2:]; ui = await get_ui(bid); cur = ui["styles"].get(key)
        ui["styles"][key] = ORDER[(ORDER.index(cur) + 1) % 3] if cur in ORDER else ORDER[0]
        await db.put(bid, "styles", json.dumps(ui["styles"])); await c.answer({"primary": "🔵", "success": "🟢", "danger": "🔴"}[ui["styles"][key]])
        await c.message.edit_reply_markup(reply_markup=await design_kb(bid, ui, [btn(ui, "back", callback_data="m:admin")]))

    @r.callback_query(F.data.startswith("e:"))
    async def edit_btn(c: CallbackQuery, state: FSMContext):
        if not await is_admin(c.bot.id, c.from_user.id): return await c.answer()
        await state.set_state(S.rename); await state.update_data(key=c.data[2:]); await c.answer()
        await c.message.answer("✏️ Yangi nomni kiriting (bekor qilish: /start):")

    @r.callback_query(F.data.startswith("ch:"))
    async def chan_cb(c: CallbackQuery, state: FSMContext):
        bid = c.bot.id
        if not await is_admin(bid, c.from_user.id): return await c.answer()
        await c.answer()
        if c.data == "ch:add":
            await state.set_state(S.chan); return await c.message.answer("📢 Kanal usernameni yuboring (masalan: @kanal):")
        ch = [x for x in json.loads(await db.get(bid, "channels", "[]")) if x != c.data[7:]]
        await db.put(bid, "channels", json.dumps(ch)); await c.message.answer("✅ Olib tashlandi.")

    @r.callback_query(F.data.startswith("u:"))
    async def user_act(c: CallbackQuery, state: FSMContext):
        bid = c.bot.id
        if not await is_admin(bid, c.from_user.id): return await c.answer()
        _, act, uid, *rest = c.data.split(":"); uid = int(uid); await c.answer("✅")
        if act == "add": await extend(bid, uid, int(rest[0]))
        elif act == "ban": await db.ex("UPDATE users SET banned=1 WHERE bot_id=? AND user_id=?", bid, uid)
        elif act == "unban": await db.ex("UPDATE users SET banned=0 WHERE bot_id=? AND user_id=?", bid, uid)
        elif act == "set":
            await state.set_state(S.udays); await state.update_data(uid=uid); return await c.message.answer("⏳ Necha kun qoldirilsin? (son kiriting)")
        await user_card(c.message, bid, uid)

    async def user_card(msg, bid, uid):
        u = await db.one("SELECT * FROM users WHERE bot_id=? AND user_id=?", bid, uid)
        if not u: return await msg.answer("❌ Topilmadi.")
        d = int((u["expires"] - time.time()) / 86400)
        rows = [[raw("➕ 7 kun", "success", callback_data=f"u:add:{uid}:7"), raw("➕ 30 kun", "success", callback_data=f"u:add:{uid}:30")],
                [raw("⏳ Kun belgilash", "primary", callback_data=f"u:set:{uid}")],
                [raw("✅ Cheklovni olish", "primary", callback_data=f"u:unban:{uid}") if u["banned"] else raw("🚫 Cheklash", "danger", callback_data=f"u:ban:{uid}")]]
        await msg.answer(f"👤 <b>{escape(u['name'] or '')}</b>\n🆔 <code>{uid}</code>\n⏳ Qoldi: <b>{d} kun</b>\n🚫 Cheklov: {'ha' if u['banned'] else 'yo`q'}", reply_markup=kb(rows))

    # --- admin matn holatlari ---
    @r.message(S.tez_acc, F.text)
    async def s_tez_acc(m: Message, state: FSMContext):
        if not await is_admin(m.bot.id, m.from_user.id): return
        await state.update_data(acc=m.text.strip()); await state.set_state(S.tez_kassa); await m.answer("🔑 Endi <b>Kassa API</b> ni kiriting:")

    @r.message(S.tez_kassa, F.text)
    async def s_tez_kassa(m: Message, state: FSMContext):
        if not await is_admin(m.bot.id, m.from_user.id): return
        d = await state.get_data(); bid = m.bot.id
        await db.put(bid, "tez_acc", d["acc"]); await db.put(bid, "tez_kassa", m.text.strip()); await db.put(bid, "tez_on", 1)
        await state.clear(); await m.answer("✅ <b>Avto to'lov yoqildi!</b> (tezcheck.uz)")
        try: await m.delete()
        except Exception: pass

    @r.message(S.click, F.text)
    async def s_click(m: Message, state: FSMContext):
        if not await is_admin(m.bot.id, m.from_user.id): return
        await db.put(m.bot.id, "click_token", m.text.strip()); await state.clear(); await m.answer("✅ Click to'lovi yoqildi.")

    async def _num(m, state, key, label):
        if not await is_admin(m.bot.id, m.from_user.id): return
        if not m.text.strip().isdigit(): return await m.answer("❌ Faqat son kiriting.")
        await db.put(m.bot.id, key, int(m.text)); await state.clear(); await m.answer(f"✅ {label} saqlandi.")
    @r.message(S.price, F.text)
    async def s_price(m: Message, state: FSMContext): await _num(m, state, "price", "Narx")
    @r.message(S.trial, F.text)
    async def s_trial(m: Message, state: FSMContext): await _num(m, state, "trial_days", "Bepul muddat")

    @r.message(S.chan, F.text)
    async def s_chan(m: Message, state: FSMContext):
        bid = m.bot.id
        if not await is_admin(bid, m.from_user.id): return
        ch = json.loads(await db.get(bid, "channels", "[]")); c = m.text.strip()
        if not c.startswith("@"): c = "@" + c
        ch.append(c); await db.put(bid, "channels", json.dumps(ch)); await state.clear(); await m.answer(f"✅ {c} qo'shildi.")

    @r.message(S.uid, F.text)
    async def s_uid(m: Message, state: FSMContext):
        if not await is_admin(m.bot.id, m.from_user.id): return
        await state.clear()
        if m.text.strip().isdigit(): await user_card(m, m.bot.id, int(m.text))
        else: await m.answer("❌ ID noto'g'ri.")

    @r.message(S.udays, F.text)
    async def s_udays(m: Message, state: FSMContext):
        if not await is_admin(m.bot.id, m.from_user.id): return
        d = await state.get_data(); await state.clear()
        if m.text.strip().lstrip("-").isdigit():
            await db.ex("UPDATE users SET expires=? WHERE bot_id=? AND user_id=?", int(time.time()) + int(m.text) * 86400, m.bot.id, d["uid"])
        await user_card(m, m.bot.id, d["uid"])

    @r.message(S.rename, F.text)
    async def s_rename(m: Message, state: FSMContext):
        bid = m.bot.id
        if not await is_admin(bid, m.from_user.id): return
        d = await state.get_data(); ui = await get_ui(bid); ui["labels"][d["key"]] = m.text.strip()[:30]
        await db.put(bid, "labels", json.dumps(ui["labels"])); await state.clear(); await m.answer("✅ Tugma nomi o'zgartirildi.")

    @r.message(S.bcast, F.text)
    async def s_bcast(m: Message, state: FSMContext):
        bid = m.bot.id
        if not await is_admin(bid, m.from_user.id): return
        await state.clear(); ok = 0
        for u in await db.all_("SELECT user_id FROM users WHERE bot_id=? AND banned=0", bid):
            try: await m.bot.send_message(u["user_id"], m.text); ok += 1
            except Exception: pass
        await m.answer(f"📣 Yuborildi: {ok}")

    # --- Business: ulanish, xabarlar ---
    @r.business_connection()
    async def on_conn(c: BusinessConnection):
        bid = c.bot.id if hasattr(c, "bot") and c.bot else None
        bot = c.bot; bid = bot.id
        await ensure_user(bid, c.user)
        if c.is_enabled:
            await db.ex("INSERT OR REPLACE INTO conns VALUES(?,?,?)", bid, c.id, c.user.id)
            await bot.send_message(c.user_chat_id, T[await lang_of(bid, c.user.id)]["connected"])

    @r.business_message()
    async def on_bm(m: Message):
        bot, bid = m.bot, m.bot.id
        owner = await conn_owner(bot, bid, m.business_connection_id)
        if not owner or not await allowed(bid, owner): return
        typ, fid, ext = extract(m); path = await dl(bot, bid, m, fid, ext) if fid else None
        await save_msg(bid, m.business_connection_id, m, typ, path)
        rp = m.reply_to_message   # o'chib ketuvchi media: egasi shu mediaga reply qilib istalgan so'z yozadi
        if rp and m.from_user and m.from_user.id == owner:
            t2, f2, e2 = extract(rp)
            if f2:
                p2 = await dl(bot, bid, rp, f2, e2)
                if p2:
                    await save_msg(bid, m.business_connection_id, rp, t2, p2)
                    lang = await lang_of(bid, owner)
                    await send_media(bot, owner, t2, p2, f"{T[lang]['saved_media']}\n👤 {escape(rp.chat.full_name or '')}")

    @r.edited_business_message()
    async def on_edit(m: Message):
        bot, bid = m.bot, m.bot.id
        owner = await conn_owner(bot, bid, m.business_connection_id)
        if not owner or not await allowed(bid, owner): return
        old = await db.one("SELECT * FROM msgs WHERE bot_id=? AND conn_id=? AND chat_id=? AND msg_id=?", bid, m.business_connection_id, m.chat.id, m.message_id)
        new = m.text or m.caption or ""
        if old and old["from_id"] != owner and old["text"] != new:
            lang = await lang_of(bid, owner); t = T[lang]
            txt = f"{t['edited']}\n👤 {escape(old['chat_name'] or '')}\n\n<b>{t['old']}:</b> {escape(old['text'] or '—')}\n<b>{t['new']}:</b> {escape(new or '—')}"
            if old["path"] and os.path.exists(old["path"]): await send_media(bot, owner, old["type"], old["path"], txt)
            else: await bot.send_message(owner, txt)
        if old: await db.ex("UPDATE msgs SET text=?, status='edited' WHERE bot_id=? AND conn_id=? AND chat_id=? AND msg_id=?", new, bid, m.business_connection_id, m.chat.id, m.message_id)
        else:
            typ, fid, ext = extract(m); await save_msg(bid, m.business_connection_id, m, typ, await dl(bot, bid, m, fid, ext) if fid else None)

    @r.deleted_business_messages()
    async def on_del(d: BusinessMessagesDeleted):
        bot, bid = d.bot, d.bot.id
        owner = await conn_owner(bot, bid, d.business_connection_id)
        if not owner or not await allowed(bid, owner): return
        t = T[await lang_of(bid, owner)]
        for mid in d.message_ids:
            row = await db.one("SELECT * FROM msgs WHERE bot_id=? AND conn_id=? AND chat_id=? AND msg_id=?", bid, d.business_connection_id, d.chat.id, mid)
            if not row: continue
            await db.ex("UPDATE msgs SET status='deleted' WHERE bot_id=? AND conn_id=? AND chat_id=? AND msg_id=?", bid, d.business_connection_id, d.chat.id, mid)
            if row["from_id"] == owner: continue
            txt = f"{t['deleted']}\n👤 {escape(row['chat_name'] or '')}\n🕒 {time.strftime('%d.%m %H:%M', time.localtime(row['date']))}\n\n{escape(row['text'] or '')}"
            if row["path"] and os.path.exists(row["path"]): await send_media(bot, owner, row["type"], row["path"], txt)
            else: await bot.send_message(owner, txt)
    return r
