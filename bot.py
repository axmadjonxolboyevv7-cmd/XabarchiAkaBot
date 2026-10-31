import json, os, time
from html import escape
from aiogram import Router, F, Bot
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (Message, CallbackQuery, BusinessConnection, BusinessMessagesDeleted,
                           FSInputFile, LabeledPrice, PreCheckoutQuery)
from aiogram.exceptions import TelegramBadRequest
import db
from config import ADMIN_IDS, TRIAL_DAYS, DEFAULT_PRICE, DEFAULT_PARTNER_PRICE, MEDIA_DIR
from ui import (T, EMOJI, ORDER, USER_KEYS, ADMIN_KEYS, get_ui, btn, rbtn, btn_text, kb, rkb, raw)
from payments import tez_create, tez_check
from pdfgen import make_pdf

class S(StatesGroup):
    tez_acc = State(); tez_kassa = State(); click = State(); trial = State(); chan = State(); uid = State(); udays = State()
    rename = State(); bcast = State(); man_card = State(); man_proof = State(); token = State(); tname = State(); tdays = State(); tprice = State(); tedit = State()

def money(n): return f"{int(n):,}".replace(",", " ")

# ---------- yordamchilar ----------
async def is_main(bid):
    r = await db.one("SELECT is_main FROM bots WHERE bot_id=?", bid); return bool(r and r["is_main"])
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

async def ensure_tariffs(bid):
    if not await db.one("SELECT 1 FROM tariffs WHERE bot_id=?", bid):
        await db.ex("INSERT INTO tariffs(bot_id,name,days,price) VALUES(?,?,?,?)", bid, "Standart", 30, DEFAULT_PRICE)

async def item_info(bid, item):
    """item: 't<id>' (tarif) yoki 'partner'. -> (nom, narx, kun)"""
    if item == "partner": return "Hamkorlik", int(await db.get(bid, "partner_price", DEFAULT_PARTNER_PRICE)), 0
    t = await db.one("SELECT * FROM tariffs WHERE id=? AND bot_id=?", int(item[1:]), bid)
    return (t["name"], t["price"], t["days"]) if t else None

async def fulfill(bid, uid, item):
    info = await item_info(bid, item)
    if not info: return None
    if item == "partner":
        await db.put(bid, f"partner:{uid}", 1)
        return "✅ Hamkorlik ochildi! <b>Hamkorlik</b> tugmasini bosib bot tokenini yuboring."
    await extend(bid, uid, info[2])
    return T[await lang_of(bid, uid)]["paid_ok"].replace("30", str(info[2]))

async def send_menu(bot, bid, uid):
    lang = await lang_of(bid, uid); ui = await get_ui(bid)
    rows = [[rbtn(ui, "connect", lang)], [rbtn(ui, "history", lang), rbtn(ui, "profile", lang)], [rbtn(ui, "pay", lang), rbtn(ui, "lang", lang)]]
    if await is_main(bid): rows.append([rbtn(ui, "partner", lang)])
    if await is_admin(bid, uid): rows.append([rbtn(ui, "admin", lang)])
    await bot.send_message(uid, T[lang]["welcome"], reply_markup=rkb(rows))

async def send_admin_menu(bot, bid, uid, text="⚙️ <b>Admin panel</b>"):
    lang = await lang_of(bid, uid); ui = await get_ui(bid); b = lambda k: rbtn(ui, k, lang)
    rows = [[b("a_stats"), b("a_users")], [b("a_trial"), b("a_tariffs")], [b("a_tez")], [b("a_click"), b("a_manual")], [b("a_channels")],
            [b("a_edit"), b("a_design")], [b("a_bcast")], [b("back")]]
    await bot.send_message(uid, text, reply_markup=rkb(rows))

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
    if typ == "video_note":
        await bot.send_video_note(chat_id, f)
        if cap: await bot.send_message(chat_id, cap)
        return
    fn = {"photo": (bot.send_photo, "photo"), "video": (bot.send_video, "video"), "voice": (bot.send_voice, "voice"),
          "audio": (bot.send_audio, "audio"), "animation": (bot.send_animation, "animation"), "document": (bot.send_document, "document")}.get(typ)
    if fn: await fn[0](chat_id, **{fn[1]: f}, caption=cap)

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

async def pay_methods(bid, item, ui, lang):
    rows = []
    if await db.get(bid, "click_token"): rows.append([btn(ui, "click", lang, callback_data=f"p:click:{item}")])
    if await db.get(bid, "tez_on"): rows.append([btn(ui, "tez", lang, callback_data=f"p:tez:{item}")])
    if await db.get(bid, "manual_card"): rows.append([btn(ui, "manual", lang, callback_data=f"p:man:{item}")])
    return rows

async def admins_of(bid):
    b = await db.one("SELECT owner_id,is_main FROM bots WHERE bot_id=?", bid)
    if not b: return []
    return list(ADMIN_IDS) if b["is_main"] else [b["owner_id"]]

# ---------- router ----------
def build_router():
    r = Router()

    # reply-klaviatura tugmasini aniqlash (state'dan oldin ishlaydi)
    async def key_filter(m: Message):
        if not m.text or m.chat.type != "private": return False
        bid = m.bot.id; ui = await get_ui(bid); lang = await lang_of(bid, m.from_user.id)
        for k in USER_KEYS + ADMIN_KEYS:
            if btn_text(ui, k, lang) == m.text: return {"key": k}
        return False

    @r.message(CommandStart())
    async def start(m: Message, state: FSMContext):
        await state.clear(); bid = m.bot.id
        u = await ensure_user(bid, m.from_user)
        if u["banned"]: return await m.answer(T["uz"]["banned"])
        if not u["lang"]: return await m.answer(T["uz"]["choose_lang"], reply_markup=lang_kb())
        await gate_menu(m.bot, bid, m.from_user.id)

    async def gate_menu(bot, bid, uid):
        lang = await lang_of(bid, uid); ui = await get_ui(bid); bad = await not_subscribed(bot, bid, uid)
        if bad:
            rows = [[raw(f"📢 {c}", "primary", url=f"https://t.me/{c.lstrip('@')}")] for c in bad] + [[btn(ui, "check", lang, callback_data="m:check")]]
            return await bot.send_message(uid, T[lang]["sub_need"], reply_markup=kb(rows))
        await send_menu(bot, bid, uid)

    @r.callback_query(F.data.startswith("l:"))
    async def setlang(c: CallbackQuery):
        await ensure_user(c.bot.id, c.from_user)
        await db.ex("UPDATE users SET lang=? WHERE bot_id=? AND user_id=?", c.data[2:], c.bot.id, c.from_user.id)
        await c.answer("✅"); await c.message.delete(); await gate_menu(c.bot, c.bot.id, c.from_user.id)

    @r.callback_query(F.data == "m:check")
    async def check_sub(c: CallbackQuery):
        await c.answer(); await c.message.delete(); await gate_menu(c.bot, c.bot.id, c.from_user.id)

    @r.message(key_filter)
    async def on_key(m: Message, key: str, state: FSMContext):
        await state.clear(); bid, uid = m.bot.id, m.from_user.id
        u = await ensure_user(bid, m.from_user)
        if u["banned"]: return await m.answer(T["uz"]["banned"])
        await do_key(m.bot, bid, uid, key, state)

    async def do_key(bot, bid, uid, key, state):
        lang = await lang_of(bid, uid); ui = await get_ui(bid); t = T[lang]; admin = await is_admin(bid, uid)
        send = lambda text, rm=None: bot.send_message(uid, text, reply_markup=rm)
        if key == "back": return await send_menu(bot, bid, uid)
        if key.startswith("a_") or key == "admin":
            if not admin: return
            if key == "admin": return await send_admin_menu(bot, bid, uid)
            asks = {"a_tez": (S.tez_acc, "⚡ <b>tezcheck.uz avto to'lov</b>\n🔑 <b>Hisob API</b> ni kiriting:"),
                    "a_click": (S.click, "💳 BotFather → Payments → Click <b>provider token</b>ni yuboring:"),
                    "a_trial": (S.trial, "⏳ Yangi foydalanuvchilar uchun bepul kun sonini kiriting:"),
                    "a_users": (S.uid, "👥 Foydalanuvchi ID raqamini kiriting:"),
                    "a_bcast": (S.bcast, "📣 Barcha foydalanuvchilarga yuboriladigan matnni kiriting:"),
                    "a_manual": (S.man_card, "🏦 <b>Qo'lda to'lov</b>\nKarta raqami va egasini bitta xabarda yuboring.\nMasalan: <code>8600 1234 5678 9012 — Ism Familiya</code>\nO'chirish uchun <code>-</code> yuboring.")}
            if key in asks:
                await state.set_state(asks[key][0]); return await send(asks[key][1])
            if key == "a_tariffs": return await show_tariffs(bot, bid, uid)
            if key == "a_stats":
                now = int(time.time()); g = lambda s, *a: db.one(s, bid, *a)
                tot = (await g("SELECT COUNT(*) n FROM users WHERE bot_id=?"))["n"]
                act = (await g("SELECT COUNT(*) n FROM users WHERE bot_id=? AND expires>? AND banned=0", now))["n"]
                ban = (await g("SELECT COUNT(*) n FROM users WHERE bot_id=? AND banned=1"))["n"]
                new = (await g("SELECT COUNT(*) n FROM users WHERE bot_id=? AND joined>?", now - 86400))["n"]
                msgs = (await g("SELECT COUNT(*) n FROM msgs WHERE bot_id=?"))["n"]
                dels = (await g("SELECT COUNT(*) n FROM msgs WHERE bot_id=? AND status='deleted'"))["n"]
                inc = (await g("SELECT COALESCE(SUM(amount),0) n FROM pays WHERE bot_id=? AND status='paid'"))["n"]
                return await send(f"📊 <b>Statistika</b>\n👥 Jami: <b>{tot}</b>\n✅ Faol: <b>{act}</b>\n🚫 Cheklangan: <b>{ban}</b>\n🆕 24 soatda: <b>{new}</b>\n💬 Saqlangan xabar: <b>{msgs}</b>\n🗑 O'chirilgan: <b>{dels}</b>\n💰 Tushum: <b>{money(inc)}</b> so'm")
            if key == "a_channels":
                ch = json.loads(await db.get(bid, "channels", "[]"))
                rows = [[raw(f"❌ {x}", "danger", callback_data=f"ch:del:{x}")] for x in ch] + [[raw("➕ Kanal qo'shish", "success", callback_data="ch:add")]]
                return await send("📢 <b>Majburiy kanallar</b>\nBotni kanalga admin qiling.", kb(rows))
            if key == "a_edit":
                rows = [[btn(ui, k, lang, callback_data=f"e:{k}")] for k in USER_KEYS + ADMIN_KEYS if k != "back"]
                return await send("✏️ Tahrirlash uchun tugmani bosing:", kb(rows))
            if key == "a_design":
                return await send("🎨 Rangni almashtirish: bosing (🔵→🟢→🔴). Tugagach «Qo'llash» ni bosing.", await design_kb(bid, ui, lang))
            return
        # --- foydalanuvchi tugmalari: majburiy obuna tekshiruvi ---
        bad = await not_subscribed(bot, bid, uid)
        if bad: return await gate_menu(bot, bid, uid)
        u = await db.one("SELECT * FROM users WHERE bot_id=? AND user_id=?", bid, uid)
        if key == "lang": return await send(T["uz"]["choose_lang"], lang_kb())
        if key == "connect":
            me = await bot.me(); txt = t["connect"].format(u=me.username)
            try: return await send(txt, kb([[btn(ui, "connect", lang, url="tg://settings")]]))
            except TelegramBadRequest: return await send(txt)
        if key == "profile":
            d = (u["expires"] - time.time()) / 86400
            left = t["left"].format(d=int(d) + 1) if d > 0 else t["expired"]
            return await send(t["profile"].format(id=uid, left=left))
        if key == "pay":
            await ensure_tariffs(bid)
            rows = [[raw(f"{x['name']} — {x['days']} kun — {money(x['price'])} so'm", "success", callback_data=f"t:buy:t{x['id']}")]
                    for x in await db.all_("SELECT * FROM tariffs WHERE bot_id=? ORDER BY days", bid)]
            return await send(t["pay_title"], kb(rows))
        if key == "history":
            rows = await db.all_("""SELECT chat_id, MAX(chat_name) n, COUNT(*) c FROM msgs WHERE bot_id=? AND conn_id IN
                (SELECT conn_id FROM conns WHERE bot_id=? AND user_id=?) GROUP BY chat_id ORDER BY MAX(date) DESC LIMIT 20""", bid, bid, uid)
            if not rows: return await send(t["no_chat"])
            return await send(t["pick_chat"], kb([[raw(f"💬 {x['n']} ({x['c']})", "primary", callback_data=f"h:{x['chat_id']}")] for x in rows]))
        if key == "partner" and await is_main(bid):
            if admin or await db.get(bid, f"partner:{uid}"):
                await state.set_state(S.token)
                return await send("🤝 <b>Hamkorlik</b>\n@BotFather da bot yarating va <b>tokenini</b> yuboring.\nBotni o'z admin paneli bilan to'liq boshqarasiz.")
            _, price, _ = await item_info(bid, "partner")
            if price <= 0:
                await fulfill(bid, uid, "partner"); return await do_key(bot, bid, uid, "partner", state)
            rows = await pay_methods(bid, "partner", ui, lang)
            if not rows: return await send(t["pay_none"])
            return await send(f"🤝 <b>Hamkorlik</b> pullik.\n💰 Narx: <b>{money(price)} so'm</b>\nTo'lov usulini tanlang:", kb(rows))

    # --- to'lovlar ---
    @r.callback_query(F.data.startswith("t:buy:"))
    async def buy(c: CallbackQuery):
        bid = c.bot.id; item = c.data[6:]; info = await item_info(bid, item); await c.answer()
        if not info: return
        lang = await lang_of(bid, c.from_user.id); rows = await pay_methods(bid, item, await get_ui(bid), lang)
        if not rows: return await c.message.answer(T[lang]["pay_none"])
        await c.message.answer(f"💎 <b>{escape(info[0])}</b> — {info[2]} kun\n💰 <b>{money(info[1])} so'm</b>\nTo'lov usulini tanlang:", reply_markup=kb(rows))

    @r.callback_query(F.data.startswith("p:click:"))
    async def p_click(c: CallbackQuery):
        bid = c.bot.id; item = c.data[8:]; info = await item_info(bid, item); await c.answer()
        if not info: return
        await c.bot.send_invoice(c.from_user.id, info[0], "Xabarlarni saqlash xizmati", item, await db.get(bid, "click_token"), "UZS",
                                 [LabeledPrice(label=info[0], amount=info[1] * 100)])

    @r.pre_checkout_query()
    async def pre(q: PreCheckoutQuery): await q.answer(ok=True)

    @r.message(F.successful_payment)
    async def paid(m: Message):
        bid, uid = m.bot.id, m.from_user.id; sp = m.successful_payment
        await db.ex("INSERT INTO pays(bot_id,user_id,method,amount,status,ref,ts,item) VALUES(?,?,?,?,?,?,?,?)", bid, uid, "click", sp.total_amount // 100, "paid", sp.provider_payment_charge_id, int(time.time()), sp.invoice_payload)
        txt = await fulfill(bid, uid, sp.invoice_payload)
        if txt: await m.answer(txt)

    @r.callback_query(F.data.startswith("p:tez:"))
    async def p_tez(c: CallbackQuery):
        bid, uid = c.bot.id, c.from_user.id; item = c.data[6:]; info = await item_info(bid, item); await c.answer()
        if not info: return
        lang = await lang_of(bid, uid); ui = await get_ui(bid)
        cur = await db.ex("INSERT INTO pays(bot_id,user_id,method,amount,status,ref,ts,item) VALUES(?,?,?,?,?,?,?,?)", bid, uid, "tez", info[1], "pending", "", int(time.time()), item)
        pid = cur.lastrowid; ref = f"TZ{bid}_{pid}"; await db.ex("UPDATE pays SET ref=? WHERE id=?", ref, pid)
        d = await tez_create(await db.get(bid, "tez_acc"), await db.get(bid, "tez_kassa"), info[1], ref, info[0])
        if not d["url"]:
            await db.ex("UPDATE pays SET status='failed' WHERE id=?", pid)
            return await c.message.answer("⚠️ To'lov havolasini yaratib bo'lmadi. Keyinroq urinib ko'ring yoki admin bilan bog'laning.")
        await c.message.answer(f"⚡ <b>{escape(info[0])}</b>\n💰 <b>{money(info[1])} so'm</b>\nQuyidagi havola orqali to'lang. To'lov avtomatik aniqlanadi.",
                               reply_markup=kb([[raw("💳 To'lash", "success", url=d["url"])], [btn(ui, "check", lang, callback_data=f"p:chk:{pid}")]]))

    @r.callback_query(F.data.startswith("p:chk:"))
    async def p_chk(c: CallbackQuery):
        bid = c.bot.id; p = await db.one("SELECT * FROM pays WHERE id=? AND bot_id=?", int(c.data[6:]), bid)
        if not p: return await c.answer()
        if p["status"] == "paid": return await c.answer("✅", show_alert=True)
        if await tez_check(await db.get(bid, "tez_acc"), await db.get(bid, "tez_kassa"), p["ref"]):
            await db.ex("UPDATE pays SET status='paid' WHERE id=?", p["id"])
            txt = await fulfill(bid, p["user_id"], p["item"]); await c.answer()
            if txt: await c.message.answer(txt)
        else: await c.answer("⏳ To'lov hali topilmadi", show_alert=True)

    @r.callback_query(F.data.startswith("h:"))
    async def hist(c: CallbackQuery):
        bid, uid, chat = c.bot.id, c.from_user.id, int(c.data[2:]); await c.answer("⏳ PDF...")
        rows = await db.all_("""SELECT * FROM msgs WHERE bot_id=? AND chat_id=? AND conn_id IN (SELECT conn_id FROM conns WHERE bot_id=? AND user_id=?)
            ORDER BY date""", bid, chat, bid, uid)
        if not rows: return
        path = os.path.join(MEDIA_DIR, f"hist_{bid}_{uid}_{chat}.pdf")
        make_pdf(path, f"Chat tarixi: {rows[0]['chat_name']}", rows)
        await c.message.answer_document(FSInputFile(path, filename=f"tarix_{chat}.pdf")); os.remove(path)

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
        await m.answer(f"✅ @{me.username} tayyor!\nBotingizga kirib /start bosing — u yerda <b>Admin panel</b> paydo bo'ladi.")

    # --- tariflar (admin) ---
    async def show_tariffs(bot, bid, uid):
        await ensure_tariffs(bid)
        rows = [[raw(f"{x['name']} • {x['days']} kun • {money(x['price'])}", "primary", callback_data=f"tf:v:{x['id']}")] for x in await db.all_("SELECT * FROM tariffs WHERE bot_id=? ORDER BY days", bid)]
        rows.append([raw("➕ Yangi tarif qo'shish", "success", callback_data="tf:new")])
        if await is_main(bid): rows.append([raw(f"🤝 Hamkorlik narxi: {money(await db.get(bid, 'partner_price', DEFAULT_PARTNER_PRICE))}", "danger", callback_data="tf:partner")])
        await bot.send_message(uid, "💰 <b>Tariflar va narxlar</b>\nTahrirlash uchun tarifni bosing:", reply_markup=kb(rows))

    @r.callback_query(F.data.startswith("tf:"))
    async def tf_cb(c: CallbackQuery, state: FSMContext):
        bid, uid = c.bot.id, c.from_user.id
        if not await is_admin(bid, uid): return await c.answer()
        p = c.data.split(":"); await c.answer()
        if p[1] == "new":
            await state.set_state(S.tname); return await c.message.answer("➕ Tarif <b>nomini</b> kiriting:")
        if p[1] == "partner":
            await state.set_state(S.tedit); await state.update_data(field="partner", id=0)
            return await c.message.answer("🤝 Hamkorlik uchun yangi narxni kiriting (so'm; 0 = bepul):")
        if p[1] == "v":
            x = await db.one("SELECT * FROM tariffs WHERE id=? AND bot_id=?", int(p[2]), bid)
            if not x: return
            rows = [[raw("✏️ Nom", "primary", callback_data=f"tf:e:name:{x['id']}"), raw("⏳ Muddat", "primary", callback_data=f"tf:e:days:{x['id']}")],
                    [raw("💰 Narx", "success", callback_data=f"tf:e:price:{x['id']}")], [raw("🗑 O'chirish", "danger", callback_data=f"tf:d:{x['id']}")]]
            return await c.message.answer(f"💎 <b>{escape(x['name'])}</b>\n⏳ {x['days']} kun\n💰 {money(x['price'])} so'm", reply_markup=kb(rows))
        if p[1] == "e":
            await state.set_state(S.tedit); await state.update_data(field=p[2], id=int(p[3]))
            return await c.message.answer({"name": "Yangi nomni", "days": "Yangi muddatni (kun)", "price": "Yangi narxni (so'm)"}[p[2]] + " kiriting:")
        if p[1] == "d":
            await db.ex("DELETE FROM tariffs WHERE id=? AND bot_id=?", int(p[2]), bid); await show_tariffs(c.bot, bid, uid)

    @r.message(S.tname, F.text)
    async def s_tname(m: Message, state: FSMContext):
        await state.update_data(name=m.text.strip()[:40]); await state.set_state(S.tdays); await m.answer("⏳ Tarif <b>muddatini</b> kiriting (kun):")

    @r.message(S.tdays, F.text)
    async def s_tdays(m: Message, state: FSMContext):
        if not m.text.strip().isdigit() or int(m.text) < 1: return await m.answer("❌ Faqat son kiriting.")
        await state.update_data(days=int(m.text)); await state.set_state(S.tprice); await m.answer("💰 Tarif <b>narxini</b> kiriting (so'm):")

    @r.message(S.tprice, F.text)
    async def s_tprice(m: Message, state: FSMContext):
        if not m.text.strip().isdigit(): return await m.answer("❌ Faqat son kiriting.")
        d = await state.get_data(); await state.clear()
        await db.ex("INSERT INTO tariffs(bot_id,name,days,price) VALUES(?,?,?,?)", m.bot.id, d["name"], d["days"], int(m.text))
        await m.answer("✅ Tarif qo'shildi."); await show_tariffs(m.bot, m.bot.id, m.from_user.id)

    @r.message(S.tedit, F.text)
    async def s_tedit(m: Message, state: FSMContext):
        bid = m.bot.id; d = await state.get_data(); f = d["field"]; v = m.text.strip()
        if f != "name" and not v.isdigit(): return await m.answer("❌ Faqat son kiriting.")
        await state.clear()
        if f == "partner": await db.put(bid, "partner_price", int(v))
        else: await db.ex(f"UPDATE tariffs SET {f}=? WHERE id=? AND bot_id=?", v[:40] if f == "name" else int(v), d["id"], bid)
        await m.answer("✅ Saqlandi."); await show_tariffs(m.bot, bid, m.from_user.id)

    # --- dizayn / tahrirlash / kanallar / foydalanuvchilar ---
    async def design_kb(bid, ui, lang):
        rows = [[btn(ui, k, lang, callback_data=f"d:{k}")] for k in USER_KEYS + ADMIN_KEYS]
        return kb(rows + [[raw("✅ Qo'llash", "success", callback_data="d:apply")]])

    @r.callback_query(F.data.startswith("d:"))
    async def design(c: CallbackQuery):
        bid, uid = c.bot.id, c.from_user.id
        if not await is_admin(bid, uid): return await c.answer()
        key = c.data[2:]
        if key == "apply":
            await c.answer("✅"); return await send_admin_menu(c.bot, bid, uid, "✅ Dizayn qo'llandi.")
        ui = await get_ui(bid); cur = ui["styles"].get(key)
        ui["styles"][key] = ORDER[(ORDER.index(cur) + 1) % 3] if cur in ORDER else ORDER[0]
        await db.put(bid, "styles", json.dumps(ui["styles"])); await c.answer({"primary": "🔵", "success": "🟢", "danger": "🔴"}[ui["styles"][key]])
        await c.message.edit_reply_markup(reply_markup=await design_kb(bid, ui, await lang_of(bid, uid)))

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
        await msg.answer(f"👤 <b>{escape(u['name'] or '')}</b>\n🆔 <code>{uid}</code>\n⏳ Qoldi: <b>{d} kun</b>\n🚫 Cheklov: {'ha' if u['banned'] else 'yoq'}", reply_markup=kb(rows))

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
        await state.clear(); await m.answer("✅ <b>Avto to'lov yoqildi!</b> (tezcheck.uz)\nEndi foydalanuvchi to'lashni bossa, bot to'lov havolasini yaratadi.")
        try: await m.delete()
        except Exception: pass

    @r.message(S.click, F.text)
    async def s_click(m: Message, state: FSMContext):
        if not await is_admin(m.bot.id, m.from_user.id): return
        await db.put(m.bot.id, "click_token", m.text.strip()); await state.clear(); await m.answer("✅ Click to'lovi yoqildi.")

    @r.message(S.trial, F.text)
    async def s_trial(m: Message, state: FSMContext):
        if not await is_admin(m.bot.id, m.from_user.id): return
        if not m.text.strip().isdigit(): return await m.answer("❌ Faqat son kiriting.")
        await db.put(m.bot.id, "trial_days", int(m.text)); await state.clear(); await m.answer("✅ Bepul muddat saqlandi.")

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
        await db.put(bid, "labels", json.dumps(ui["labels"])); await state.clear()
        await send_admin_menu(m.bot, bid, m.from_user.id, "✅ Tugma nomi o'zgartirildi.")

    @r.message(S.bcast, F.text)
    async def s_bcast(m: Message, state: FSMContext):
        bid = m.bot.id
        if not await is_admin(bid, m.from_user.id): return
        await state.clear(); ok = 0
        for u in await db.all_("SELECT user_id FROM users WHERE bot_id=? AND banned=0", bid):
            try: await m.bot.send_message(u["user_id"], m.text); ok += 1
            except Exception: pass
        await m.answer(f"📣 Yuborildi: {ok}")

    # --- qo'lda to'lov (karta + chek) ---
    @r.message(S.man_card, F.text)
    async def s_man_card(m: Message, state: FSMContext):
        if not await is_admin(m.bot.id, m.from_user.id): return
        v = m.text.strip(); await db.put(m.bot.id, "manual_card", "" if v == "-" else v); await state.clear()
        await m.answer("✅ Qo'lda to'lov o'chirildi." if v == "-" else "✅ Qo'lda to'lov yoqildi. Chekni tasdiqlash uchun adminda bot ochiq bo'lishi kerak.")

    @r.callback_query(F.data.startswith("p:man:"))
    async def p_man(c: CallbackQuery, state: FSMContext):
        bid, uid = c.bot.id, c.from_user.id; item = c.data[6:]; info = await item_info(bid, item); card = await db.get(bid, "manual_card"); await c.answer()
        if not info or not card: return
        cur = await db.ex("INSERT INTO pays(bot_id,user_id,method,amount,status,ref,ts,item) VALUES(?,?,?,?,?,?,?,?)", bid, uid, "manual", info[1], "waiting", "", int(time.time()), item)
        await state.set_state(S.man_proof); await state.update_data(pid=cur.lastrowid)
        await c.message.answer(f"🏦 <b>Karta orqali to'lov</b>\n💎 {escape(info[0])}\n💰 Aynan <b>{money(info[1])} so'm</b> o'tkazing:\n\n<code>{escape(card)}</code>\n\n📸 To'lagach <b>chek (skrinshot)</b>ni shu yerga yuboring.")

    @r.message(S.man_proof, F.photo | F.document)
    async def s_proof(m: Message, state: FSMContext):
        bid, uid = m.bot.id, m.from_user.id; d = await state.get_data()
        p = await db.one("SELECT * FROM pays WHERE id=? AND bot_id=? AND status='waiting'", d.get("pid"), bid); await state.clear()
        if not p: return await m.answer("❌ Buyurtma topilmadi. To'lovni qaytadan boshlang.")
        await db.ex("UPDATE pays SET status='review' WHERE id=?", p["id"]); info = await item_info(bid, p["item"])
        cap = f"🧾 <b>Yangi to'lov cheki</b>\n👤 {escape(m.from_user.full_name)} (<code>{uid}</code>)\n💎 {escape(info[0] if info else '?')}\n💰 {money(p['amount'])} so'm"
        rm = kb([[raw("✅ Tasdiqlash", "success", callback_data=f"mp:ok:{p['id']}"), raw("❌ Rad etish", "danger", callback_data=f"mp:no:{p['id']}")]])
        for a in await admins_of(bid):
            try:
                if m.photo: await m.bot.send_photo(a, m.photo[-1].file_id, caption=cap, reply_markup=rm)
                else: await m.bot.send_document(a, m.document.file_id, caption=cap, reply_markup=rm)
            except Exception: pass
        await m.answer("✅ Chek yuborildi. Admin tasdiqlagach obuna yoqiladi.")

    @r.message(S.man_proof, F.text)
    async def s_proof_hint(m: Message): await m.answer("📸 Iltimos, to'lov chekini rasm (skrinshot) ko'rinishida yuboring.")

    @r.callback_query(F.data.startswith("mp:"))
    async def mp_cb(c: CallbackQuery):
        bid = c.bot.id
        if not await is_admin(bid, c.from_user.id): return await c.answer()
        _, act, pid = c.data.split(":"); p = await db.one("SELECT * FROM pays WHERE id=? AND bot_id=?", int(pid), bid)
        if not p or p["status"] != "review": return await c.answer("Allaqachon ko'rib chiqilgan", show_alert=True)
        await c.answer("✅")
        try: await c.message.edit_reply_markup(reply_markup=None)
        except Exception: pass
        if act == "ok":
            await db.ex("UPDATE pays SET status='paid' WHERE id=?", p["id"]); txt = await fulfill(bid, p["user_id"], p["item"])
            await c.message.answer("✅ Tasdiqlandi.")
            try: await c.bot.send_message(p["user_id"], txt or "✅")
            except Exception: pass
        else:
            await db.ex("UPDATE pays SET status='rejected' WHERE id=?", p["id"]); await c.message.answer("❌ Rad etildi.")
            try: await c.bot.send_message(p["user_id"], "❌ To'lov cheki rad etildi. Savollar bo'lsa admin bilan bog'laning.")
            except Exception: pass

    # --- Business: ulanish, xabarlar ---
    @r.business_connection()
    async def on_conn(c: BusinessConnection):
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
