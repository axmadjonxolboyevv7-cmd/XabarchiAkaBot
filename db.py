import aiosqlite
from config import DB_PATH
_db = None
SCHEMA = """
CREATE TABLE IF NOT EXISTS kv(bot_id INT, key TEXT, value TEXT, PRIMARY KEY(bot_id,key));
CREATE TABLE IF NOT EXISTS bots(bot_id INT PRIMARY KEY, token TEXT, username TEXT, owner_id INT, is_main INT DEFAULT 0);
CREATE TABLE IF NOT EXISTS users(bot_id INT, user_id INT, lang TEXT, name TEXT, joined INT, expires INT, banned INT DEFAULT 0, PRIMARY KEY(bot_id,user_id));
CREATE TABLE IF NOT EXISTS conns(bot_id INT, conn_id TEXT, user_id INT, PRIMARY KEY(bot_id,conn_id));
CREATE TABLE IF NOT EXISTS msgs(bot_id INT, conn_id TEXT, chat_id INT, msg_id INT, chat_name TEXT, from_id INT, from_name TEXT,
  type TEXT, text TEXT, path TEXT, date INT, status TEXT DEFAULT 'ok', PRIMARY KEY(bot_id,conn_id,chat_id,msg_id));
CREATE TABLE IF NOT EXISTS pays(id INTEGER PRIMARY KEY AUTOINCREMENT, bot_id INT, user_id INT, method TEXT, amount INT, status TEXT, ref TEXT, ts INT);
"""
async def init():
    global _db
    _db = await aiosqlite.connect(DB_PATH)
    _db.row_factory = aiosqlite.Row
    await _db.executescript(SCHEMA); await _db.commit()
async def ex(sql, *a):
    c = await _db.execute(sql, a); await _db.commit(); return c
async def one(sql, *a):
    c = await _db.execute(sql, a); return await c.fetchone()
async def all_(sql, *a):
    c = await _db.execute(sql, a); return await c.fetchall()
async def get(bid, key, default=None):
    r = await one("SELECT value FROM kv WHERE bot_id=? AND key=?", bid, key)
    return r["value"] if r else default
async def put(bid, key, val):
    await ex("INSERT INTO kv VALUES(?,?,?) ON CONFLICT(bot_id,key) DO UPDATE SET value=excluded.value", bid, key, str(val))
