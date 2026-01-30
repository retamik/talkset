import httpx
from aiogram import Bot, Dispatcher, F, types
from config import settings

bot = Bot(token=settings.bot_token)
dp = Dispatcher()


@dp.message(F.text)
async def on_message(msg: types.Message):
    if msg.from_user and msg.from_user.is_bot:
        return

    payload = {
        "chat_id": str(msg.chat.id),
        "text": msg.text,
        "user_id": str(msg.from_user.id) if msg.from_user else None,
        "user_name": msg.from_user.full_name if msg.from_user else None,
        "message_id": str(msg.message_id),
        "sent_at": int(msg.date.timestamp()) if msg.date else None,
    }

    async with httpx.AsyncClient(timeout=20) as client:
        try:
            await client.post(f"{settings.backend_url}/telegram/message", json=payload)
        except Exception as e:
            print(f"Ошибка при отправке на backend: {e}")


async def start_bot():
    print("🤖 Telegram bot started")
    await dp.start_polling(bot)
