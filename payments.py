"""tezcheck.uz adapteri.
DIQQAT: tezcheck.uz rasmiy API hujjati menga ochiq topilmadi. Quyidagi endpoint/maydonlar
umumiy shablon — tezcheck.uz hujjatiga qarab faqat shu faylni to'g'rilang."""
import aiohttp
from config import TEZCHECK_BASE

async def _post(path, payload):
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as s:
        async with s.post(f"{TEZCHECK_BASE}{path}", json=payload) as r:
            try: return await r.json(content_type=None)
            except Exception: return {}

async def tez_create(account_api, cashbox_api, amount, order_id):
    d = await _post("/create", {"account_api": account_api, "cashbox_api": cashbox_api,
                                "amount": amount, "order_id": order_id})
    return d or {}

async def tez_check(account_api, cashbox_api, order_id) -> bool:
    d = await _post("/check", {"account_api": account_api, "cashbox_api": cashbox_api, "order_id": order_id})
    st = str((d or {}).get("status", "")).lower()
    return st in ("paid", "success", "done", "completed")
