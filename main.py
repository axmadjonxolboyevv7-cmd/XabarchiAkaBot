import asyncio, logging
import db
from config import BOT_TOKEN
from manager import make_bot, run, poller

async def main():
    logging.basicConfig(level=logging.INFO)
    await db.init()
    main_bot = make_bot(BOT_TOKEN); me = await main_bot.get_me()
    await db.ex("INSERT INTO bots VALUES(?,?,?,0,1) ON CONFLICT(bot_id) DO UPDATE SET token=excluded.token, is_main=1", me.id, BOT_TOKEN, me.username)
    tasks = [run(main_bot), poller()]
    for b in await db.all_("SELECT token FROM bots WHERE is_main=0"): tasks.append(run(make_bot(b["token"])))
    await asyncio.gather(*tasks)

if __name__ == "__main__": asyncio.run(main())
