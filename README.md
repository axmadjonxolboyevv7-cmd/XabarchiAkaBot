# XabarBot — o'chirilgan/tahrirlangan xabarlarni saqlovchi Telegram bot

## Ishga tushirish
1. @BotFather → botni yarating → **Bot Settings → Business Mode** ni yoqing (shart!).
2. `cp .env.example .env` va to'ldiring. `pip install -r requirements.txt && python main.py`
3. GitHub'ga push qiling. Secrets: `SSH_HOST`, `SSH_USER`, `SSH_KEY`, `APP_DIR` (serverda `.env` va Docker bo'lsin). `main` ga push = avto deploy.

## Muhim eslatmalar
- **Premium emoji**: `ui.py` → `EMOJI` dagi bo'sh ID joylarga custom emoji ID yozing (bot egasida Premium bo'lishi kerak). ID bo'lmasa oddiy emoji chiqadi.
- **Rangli tugmalar**: Bot API `style` maydoni (ko'k/yashil/qizil) ishlatiladi — yangi Telegram versiyalari kerak.
- **tezcheck.uz**: `payments.py` — endpoint/maydonlar shablon, tezcheck hujjatiga qarab moslang.
- **Click**: Admin → Click sozlash → BotFather → Payments dagi token.
- **O'chib ketuvchi media**: egasi o'sha mediaga **reply** qilib istalgan so'z yozsa, bot saqlab yuboradi (Telegram boshqa yo'l bermaydi).
- **Hamkorlik**: foydalanuvchi token yuboradi → klon bot ishga tushadi; klon admin paneli faqat klon egasiga ko'rinadi.
