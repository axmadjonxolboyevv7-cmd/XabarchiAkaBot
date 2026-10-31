"""tezcheck.uz adapteri — to'lov LINKI yaratadi va holatini tekshiradi.
DIQQAT: tezcheck.uz rasmiy API hujjati menga ochiq topilmadi. Endpoint yo'llari .env orqali
(TEZCHECK_BASE, TEZCHECK_CREATE_PATH, TEZCHECK_CHECK_PATH), maydon nomlari esa shu faylda — hujjatga qarab to'g'rilang."""
import logging
import aiohttp
from config import TEZCHECK_BASE, TEZCHECK_CREATE_PATH, TEZCHECK_CHECK_PATH

def _find(d, names):
    if isinstance(d, dict):
        for k, v in d.items():
            if k.lower() in names and isinstance(v, str) and v: return v
        for v in d.values():
            r = _find(v, names)
            if r: return r
    elif isinstance(d, list):
        for v in d:
            r = _find(v, names)
            if r: return r
    return None

async def _post(path, acc, kassa, payload):
    headers = {"Authorization": f"Bearer {kassa}", "X-Account-Api": acc, "X-Cashbox-Api": kassa}
    body = {"account_api": acc, "cashbox_api": kassa, **payload}
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as s:
            async with s.post(f"{TEZCHECK_BASE}{path}", json=body, headers=headers) as r:
                try: return await r.json(content_type=None)
                except Exception: return {}
    except Exception:
        logging.exception("tezcheck so'rovi xato"); return {}

async def tez_create(acc, kassa, amount, order_id, description=""):
    d = await _post(TEZCHECK_CREATE_PATH, acc, kassa, {"amount": amount, "order_id": order_id, "description": description})
    url = _find(d, {"url", "link", "pay_url", "payment_url", "checkout_url", "payment_link"})
    if not url: logging.warning("tezcheck link qaytmadi: %s", d)
    return {"url": url, "raw": d}

async def tez_check(acc, kassa, order_id) -> bool:
    d = await _post(TEZCHECK_CHECK_PATH, acc, kassa, {"order_id": order_id})
    st = (_find(d, {"status", "state"}) or "").lower()
    return st in ("paid", "success", "done", "completed", "succeeded")
