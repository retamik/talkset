import threading
import asyncio
import uvicorn

from backend.main import app
from bot.bot import start_bot


def run_backend():
    uvicorn.run(app, host="127.0.0.1", port=8000)


def run_bot():
    asyncio.run(start_bot())


if __name__ == "__main__":
    print("🚀 Starting backend...")
    backend_thread = threading.Thread(target=run_backend, daemon=True)
    backend_thread.start()

    print("🤖 Starting Telegram bot...")
    run_bot()
