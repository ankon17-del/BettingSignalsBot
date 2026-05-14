import asyncio
import logging

from aiogram import Bot, Dispatcher
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.bot.handlers import configure_bot_menu, router
from app.config import get_settings
from app.db.session import create_db_engine, dispose_db_engine, init_db


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = get_settings()

    create_db_engine(settings.database_url)
    await init_db()

    bot = Bot(token=settings.bot_token)
    await configure_bot_menu(bot)
    dp = Dispatcher()
    dp.include_router(router)

    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.start()

    try:
        logging.info("Betting Signals Bot worker started")
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown(wait=False)
        await bot.session.close()
        await dispose_db_engine()


if __name__ == "__main__":
    asyncio.run(main())
