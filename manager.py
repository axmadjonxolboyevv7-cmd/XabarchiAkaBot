import asyncio, logging
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
import db
from payments import tez_check

registry: dict[int, Bot] = {}

def make_bot(token): return Bot(token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))

async def run(bot: Bot):
    from bot import build_router
    me = await bot.get_me(); registry[me.id] = bot
    dp = Dispatcher(storage=MemoryStorage()); dp.include_router(build_router())
    logging.info("Ishga tushdi: @%s", me.username)
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types(), handle_signals=False)

async def start_clone(token): asyncio.create_task(run(make_bot(token)))

async def poller():
    """tezcheck to'lovlarini avtomatik tekshiradi (har 20 soniya)."""
    import time
    from bot import extend
    from ui import T
    while True:
        try:
            for p in await db.all_("SELECT * FROM pays WHERE method='tez' AND status='pending' AND ts>?", int(time.time()) - 3600):
                bid = p["bot_id"]
                if await tez_check(await db.get(bid, "tez_acc"), await db.get(bid, "tez_kassa"), p["ref"]):
                    await db.ex("UPDATE pays SET status='paid' WHERE id=?", p["id"]); await extend(bid, p["user_id"], 30)
                    u = await db.one("SELECT lang FROM users WHERE bot_id=? AND user_id=?", bid, p["user_id"])
                    if bid in registry: await registry[bid].send_message(p["user_id"], T[(u and u["lang"]) or "uz"]["paid_ok"])
        except Exception: logging.exception("poller")
        await asyncio.sleep(20)
