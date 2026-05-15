import asyncio
import logging
from datetime import datetime, timezone

from aiogram import Bot, Dispatcher
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.bot.handlers import configure_bot_menu, router
from app.bot.keyboards import signal_keyboard
from app.bot.messages import olimp_generation_summary, signal_message
from app.config import get_settings
from app.db.session import create_db_engine, dispose_db_engine, init_db, session_context
from app.services.bankroll_service import BankrollService
from app.services.olimp_signal_service import OlimpSignalGenerationService
from app.services.runtime_state import update_scheduler_status


logger = logging.getLogger(__name__)


async def run_scheduled_olimp_scan(bot: Bot) -> None:
    settings = get_settings()
    if not settings.auto_olimp_scan_enabled:
        logger.debug("AUTO_OLIMP_SCAN is disabled; skipping scheduled run")
        update_scheduler_status(
            enabled=False,
            last_result="skipped",
            last_message="AUTO_OLIMP_SCAN выключен.",
        )
        return
    if not settings.olimp_enabled:
        logger.warning("AUTO_OLIMP_SCAN is enabled but OLIMP feed is disabled")
        update_scheduler_status(
            enabled=True,
            last_result="skipped",
            last_message="OLIMP feed выключен.",
        )
        return
    if settings.admin_user_id is None:
        logger.warning("AUTO_OLIMP_SCAN is enabled but ADMIN_USER_ID is not set")
        update_scheduler_status(
            enabled=True,
            last_result="skipped",
            last_message="ADMIN_USER_ID не задан.",
        )
        return

    summary_text: str | None = None
    created_signals = []
    bankroll_after = settings.default_bankroll
    update_scheduler_status(
        enabled=True,
        interval_minutes=settings.auto_olimp_scan_interval_minutes,
        match_limit=settings.auto_olimp_scan_match_limit,
        send_empty_runs=settings.auto_olimp_scan_send_empty,
        last_started_at=datetime.now(timezone.utc),
        last_result="running",
        last_message="Идет фоновый прогон OLIMP.",
        last_error=None,
    )

    try:
        async with session_context() as session:
            bankroll_service = BankrollService(session, settings)
            admin_user = await bankroll_service.get_or_create_user(settings.admin_user_id, None)
            generation_service = OlimpSignalGenerationService(session, settings)
            generation = await generation_service.generate_signals(
                admin_user,
                match_limit=max(settings.auto_olimp_scan_match_limit, settings.olimp_max_signals_per_run, 6),
                create_limit=settings.olimp_max_signals_per_run,
            )
            created_signals = list(generation.created_signals)
            bankroll_after = admin_user.bankroll
            if created_signals or settings.auto_olimp_scan_send_empty:
                summary_text = olimp_generation_summary(
                    generation,
                    create_limit=settings.olimp_max_signals_per_run,
                    league_filter=None,
                )
            update_scheduler_status(
                last_finished_at=datetime.now(timezone.utc),
                last_result="success-created" if created_signals else "success-empty",
                last_message=(
                    f"Создано сигналов: {len(created_signals)}."
                    if created_signals
                    else "Новых сигналов не найдено."
                ),
                created_signals=len(created_signals),
                passed_filters_matches=generation.passed_filters_matches,
                existing_pending_matches=generation.existing_pending_matches,
                cooldown_blocked_matches=generation.cooldown_blocked_matches,
            )
    except Exception:
        logger.exception("Scheduled OLIMP scan failed")
        update_scheduler_status(
            last_finished_at=datetime.now(timezone.utc),
            last_result="error",
            last_message="Фоновый прогон завершился ошибкой.",
            last_error="Scheduled OLIMP scan failed. Check Railway logs.",
        )
        try:
            await bot.send_message(settings.admin_user_id, "⚠️ Scheduled OLIMP scan failed. Check Railway logs.")
        except Exception:
            logger.exception("Failed to notify admin about scheduled OLIMP scan error")
        return

    if summary_text is None:
        logger.info("Scheduled OLIMP scan finished with no new signals")
        return

    try:
        await bot.send_message(settings.admin_user_id, summary_text)
        for signal in created_signals[: settings.olimp_max_signals_per_run]:
            await bot.send_message(
                settings.admin_user_id,
                signal_message(signal, bankroll_after),
                reply_markup=signal_keyboard(signal.id),
            )
    except Exception:
        logger.exception("Failed to send scheduled OLIMP scan results to admin")


def configure_scheduler(scheduler: AsyncIOScheduler, bot: Bot) -> None:
    settings = get_settings()
    if not settings.auto_olimp_scan_enabled:
        logger.info("APScheduler is running without OLIMP auto-scan job")
        update_scheduler_status(
            configured=False,
            enabled=False,
            interval_minutes=settings.auto_olimp_scan_interval_minutes,
            match_limit=settings.auto_olimp_scan_match_limit,
            send_empty_runs=settings.auto_olimp_scan_send_empty,
            last_message="Фоновый OLIMP scan не включен.",
        )
        return

    scheduler.add_job(
        run_scheduled_olimp_scan,
        trigger="interval",
        minutes=settings.auto_olimp_scan_interval_minutes,
        kwargs={"bot": bot},
        id="olimp_auto_scan",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )
    logger.info(
        "Configured OLIMP auto-scan every %s minutes with match limit %s",
        settings.auto_olimp_scan_interval_minutes,
        settings.auto_olimp_scan_match_limit,
    )
    update_scheduler_status(
        configured=True,
        enabled=True,
        interval_minutes=settings.auto_olimp_scan_interval_minutes,
        match_limit=settings.auto_olimp_scan_match_limit,
        send_empty_runs=settings.auto_olimp_scan_send_empty,
        last_message="Scheduler запущен и ждет следующий прогон.",
    )


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
    configure_scheduler(scheduler, bot)
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
