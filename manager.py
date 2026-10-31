import asyncio, logging, time
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
    from bot import fulfill
    while True:
        try:
            for p in await db.all_("SELECT * FROM pays WHERE method='tez' AND status='pending' AND ts>?", int(time.time()) - 7200):
                bid = p["bot_id"]
                if await tez_check(await db.get(bid, "tez_acc"), await db.get(bid, "tez_kassa"), p["ref"]):
                    await db.ex("UPDATE pays SET status='paid' WHERE id=?", p["id"])
                    txt = await fulfill(bid, p["user_id"], p["item"])
                    if bid in registry and txt: await registry[bid].send_message(p["user_id"], txt)
        except Exception: logging.exception("poller")
        await asyncio.sleep(20)
