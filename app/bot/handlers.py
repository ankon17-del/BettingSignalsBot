from contextlib import asynccontextmanager

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import BotCommand, CallbackQuery, MenuButtonCommands, Message

from app.bot.keyboards import back_to_signal_keyboard, main_menu_keyboard, risk_profile_keyboard, signal_keyboard
from app.bot.messages import (
    HELP,
    WELCOME,
    bankroll_message,
    money,
    olimp_candidates_summary_message,
    olimp_digest_summary_message,
    olimp_generation_debug_message,
    olimp_generation_summary,
    olimp_leagues_message,
    runtime_config_message,
    scheduler_status_message,
    signal_message,
    signal_news_message,
    stats_message,
)
from app.config import get_settings
from app.db.session import session_context
from app.services.bankroll_service import BankrollService
from app.services.odds_service import OddsFeedService
from app.services.olimp_signal_service import OlimpSignalGenerationService
from app.services.runtime_state import get_scheduler_status
from app.services.signal_service import SignalService
from app.services.stats_service import StatsService

router = Router()

BOT_COMMANDS = [
    BotCommand(command="start", description="Главное меню"),
    BotCommand(command="bankroll", description="Текущий банкролл"),
    BotCommand(command="signals", description="Активные сигналы"),
    BotCommand(command="stats", description="Статистика"),
    BotCommand(command="risk_profile", description="Профиль риска"),
    BotCommand(command="fetch_olimp_demo", description="Shortlist OLIMP"),
    BotCommand(command="fetch_olimp_candidates", description="Candidates OLIMP"),
    BotCommand(command="fetch_olimp_leagues", description="Leagues OLIMP"),
    BotCommand(command="debug_olimp_generation", description="Debug OLIMP"),
    BotCommand(command="show_runtime_config", description="Runtime config"),
    BotCommand(command="show_scheduler_status", description="Scheduler status"),
    BotCommand(command="generate_olimp_signals", description="Draft signals OLIMP"),
    BotCommand(command="help", description="Справка"),
]


@asynccontextmanager
async def get_user_context(message_or_callback: Message | CallbackQuery):
    settings = get_settings()
    async with session_context() as session:
        tg_user = message_or_callback.from_user
        bankroll_service = BankrollService(session, settings)
        user = await bankroll_service.get_or_create_user(tg_user.id, tg_user.username)
        yield session, settings, user, bankroll_service, SignalService(session), StatsService(session)


async def configure_bot_menu(bot) -> None:
    await bot.set_my_commands(BOT_COMMANDS)
    await bot.set_chat_menu_button(menu_button=MenuButtonCommands())


async def edit_or_send(message: Message, text: str, reply_markup=None) -> None:
    try:
        await message.edit_text(text, reply_markup=reply_markup)
    except Exception:
        await message.answer(text, reply_markup=reply_markup)


def is_admin(telegram_user_id: int, admin_user_id: int | None) -> bool:
    return admin_user_id is not None and telegram_user_id == admin_user_id


@router.message(Command("start"))
async def start(message: Message) -> None:
    async with get_user_context(message):
        await message.answer(WELCOME, reply_markup=main_menu_keyboard())


@router.message(Command("help"))
async def help_command(message: Message) -> None:
    await message.answer(HELP, reply_markup=main_menu_keyboard())


@router.message(Command("bankroll"))
async def bankroll(message: Message) -> None:
    async with get_user_context(message) as (
        _session,
        _settings,
        user,
        _bankroll_service,
        _signal_service,
        stats_service,
    ):
        stats = await stats_service.get_stats(user)
        await message.answer(bankroll_message(user, stats), reply_markup=main_menu_keyboard())


@router.message(Command("set_bankroll"))
async def set_bankroll(message: Message, command: CommandObject) -> None:
    amount = parse_positive_float(command.args)
    if amount is None:
        await message.answer("Использование: /set_bankroll 100000")
        return
    async with get_user_context(message) as (
        _session,
        _settings,
        user,
        bankroll_service,
        _signal_service,
        _stats_service,
    ):
        await bankroll_service.set_bankroll(user, amount)
        await message.answer(f"✅ Банкролл обновлен: {money(user.bankroll)} ₽")


@router.message(Command("set_unit"))
async def set_unit(message: Message, command: CommandObject) -> None:
    unit = parse_positive_float(command.args)
    if unit is None or unit > 10:
        await message.answer("Использование: /set_unit 1\nЗначение должно быть больше 0 и не выше 10%.")
        return
    async with get_user_context(message) as (
        _session,
        _settings,
        user,
        bankroll_service,
        _signal_service,
        _stats_service,
    ):
        await bankroll_service.set_unit_percent(user, unit)
        await message.answer(f"✅ Базовый unit обновлен: {user.base_unit_percent:.2f}%")


@router.message(Command("risk_profile"))
async def risk_profile(message: Message) -> None:
    await message.answer("Выберите профиль риска:", reply_markup=risk_profile_keyboard())


@router.message(Command("signals"))
async def signals(message: Message) -> None:
    async with get_user_context(message) as (
        _session,
        _settings,
        user,
        _bankroll_service,
        signal_service,
        _stats_service,
    ):
        active = await signal_service.list_active_signals()
        if not active:
            await message.answer("Активных сигналов пока нет. Админ может создать демо через /add_test_signal.")
            return
        for signal in active:
            await message.answer(signal_message(signal, user.bankroll), reply_markup=signal_keyboard(signal.id))


@router.message(Command("stats"))
async def stats(message: Message, command: CommandObject) -> None:
    filters = parse_filters(command.args)
    async with get_user_context(message) as (
        _session,
        _settings,
        user,
        _bankroll_service,
        _signal_service,
        stats_service,
    ):
        data = await stats_service.get_stats(
            user,
            league=filters.get("league"),
            market=filters.get("market"),
            risk_level=filters.get("risk") or filters.get("risk_level"),
            confidence=filters.get("confidence"),
            month=filters.get("month"),
        )
        await message.answer(stats_message(data), reply_markup=main_menu_keyboard())


@router.message(Command("add_test_signal"))
async def add_test_signal(message: Message) -> None:
    async with get_user_context(message) as (
        _session,
        settings,
        user,
        _bankroll_service,
        signal_service,
        _stats_service,
    ):
        if not is_admin(message.from_user.id, settings.admin_user_id):
            await message.answer("⛔ Команда доступна только администратору.")
            return
        signal = await signal_service.create_test_signal(user)
        await message.answer("✅ Демо-сигнал создан")
        await message.answer(signal_message(signal, user.bankroll), reply_markup=signal_keyboard(signal.id))


@router.message(Command("fetch_olimp_demo"))
async def fetch_olimp_demo(message: Message, command: CommandObject) -> None:
    settings = get_settings()
    if not is_admin(message.from_user.id, settings.admin_user_id):
        await message.answer("⛔ Команда доступна только администратору.")
        return

    filters = parse_filters(command.args)
    requested_limit = parse_positive_int(filters.get("limit")) or 5
    league_filter = filters.get("league")

    odds_service = OddsFeedService(settings)
    try:
        selections = await odds_service.fetch_olimp_filtered_selections(
            match_limit=requested_limit,
            markets_per_match=3,
            league_filter=league_filter,
        )
    except Exception as exc:
        await message.answer(f"Не удалось получить открытую линию OLIMP: {exc}")
        return

    await message.answer(
        olimp_digest_summary_message(selections, league_filter=league_filter, match_limit=requested_limit),
        reply_markup=main_menu_keyboard(),
    )


@router.message(Command("fetch_olimp_candidates"))
async def fetch_olimp_candidates(message: Message, command: CommandObject) -> None:
    settings = get_settings()
    if not is_admin(message.from_user.id, settings.admin_user_id):
        await message.answer("⛔ Команда доступна только администратору.")
        return

    filters = parse_filters(command.args)
    requested_limit = parse_positive_int(filters.get("limit")) or 5
    league_filter = filters.get("league")

    odds_service = OddsFeedService(settings)
    try:
        candidates = await odds_service.fetch_olimp_candidates(
            match_limit=requested_limit,
            markets_per_match=3,
            league_filter=league_filter,
        )
    except Exception as exc:
        await message.answer(f"Не удалось собрать кандидатов OLIMP: {exc}")
        return

    await message.answer(
        olimp_candidates_summary_message(candidates, league_filter=league_filter, match_limit=requested_limit),
        reply_markup=main_menu_keyboard(),
    )


@router.message(Command("fetch_olimp_leagues"))
async def fetch_olimp_leagues(message: Message, command: CommandObject) -> None:
    settings = get_settings()
    if not is_admin(message.from_user.id, settings.admin_user_id):
        await message.answer("⛔ Команда доступна только администратору.")
        return

    filters = parse_filters(command.args)
    requested_limit = parse_positive_int(filters.get("limit")) or 20
    query = filters.get("query")

    odds_service = OddsFeedService(settings)
    try:
        leagues = await odds_service.fetch_olimp_leagues(limit=requested_limit, query=query)
    except Exception as exc:
        await message.answer(f"Не удалось собрать список лиг OLIMP: {exc}")
        return

    await message.answer(
        olimp_leagues_message(leagues, query=query, limit=requested_limit),
        reply_markup=main_menu_keyboard(),
    )


@router.message(Command("debug_olimp_generation"))
async def debug_olimp_generation(message: Message, command: CommandObject) -> None:
    settings = get_settings()
    if not is_admin(message.from_user.id, settings.admin_user_id):
        await message.answer("⛔ Команда доступна только администратору.")
        return

    filters = parse_filters(command.args)
    requested_limit = parse_positive_int(filters.get("limit")) or 5
    league_filter = filters.get("league")

    async with get_user_context(message) as (
        session,
        _settings,
        _user,
        _bankroll_service,
        _signal_service,
        _stats_service,
    ):
        generation_service = OlimpSignalGenerationService(session, settings)
        try:
            entries = await generation_service.inspect_generation(
                match_limit=requested_limit,
                league_filter=league_filter,
            )
        except Exception as exc:
            await message.answer(f"Не удалось собрать debug по генерации OLIMP: {exc}")
            return

    await message.answer(
        olimp_generation_debug_message(entries, league_filter=league_filter, limit=requested_limit),
        reply_markup=main_menu_keyboard(),
    )


@router.message(Command("show_runtime_config"))
async def show_runtime_config(message: Message) -> None:
    settings = get_settings()
    if not is_admin(message.from_user.id, settings.admin_user_id):
        await message.answer("⛔ Команда доступна только администратору.")
        return

    await message.answer(runtime_config_message(settings), reply_markup=main_menu_keyboard())


@router.message(Command("show_scheduler_status"))
async def show_scheduler_status(message: Message) -> None:
    settings = get_settings()
    if not is_admin(message.from_user.id, settings.admin_user_id):
        await message.answer("⛔ Команда доступна только администратору.")
        return

    await message.answer(scheduler_status_message(get_scheduler_status()), reply_markup=main_menu_keyboard())


@router.message(Command("generate_olimp_signals"))
async def generate_olimp_signals(message: Message, command: CommandObject) -> None:
    filters = parse_filters(command.args)
    requested_limit = parse_positive_int(filters.get("limit"))
    league_filter = filters.get("league")

    async with get_user_context(message) as (
        session,
        settings,
        user,
        _bankroll_service,
        _signal_service,
        _stats_service,
    ):
        if not is_admin(message.from_user.id, settings.admin_user_id):
            await message.answer("⛔ Команда доступна только администратору.")
            return

        generation_service = OlimpSignalGenerationService(session, settings)
        try:
            generation = await generation_service.generate_signals(
                user,
                match_limit=max(requested_limit or settings.olimp_max_signals_per_run, 6),
                create_limit=requested_limit,
                league_filter=league_filter,
            )
        except Exception as exc:
            await message.answer(f"Не удалось сгенерировать draft signals OLIMP: {exc}")
            return

        await message.answer(
            olimp_generation_summary(
                generation,
                create_limit=requested_limit or settings.olimp_max_signals_per_run,
                league_filter=league_filter,
            ),
            reply_markup=main_menu_keyboard(),
        )
        for signal in generation.created_signals[:5]:
            await message.answer(signal_message(signal, user.bankroll), reply_markup=signal_keyboard(signal.id))


@router.callback_query(F.data.startswith("risk:"))
async def set_risk_profile_callback(callback: CallbackQuery) -> None:
    profile = callback.data.split(":", 1)[1]
    async with get_user_context(callback) as (
        _session,
        _settings,
        user,
        bankroll_service,
        _signal_service,
        stats_service,
    ):
        await bankroll_service.set_risk_profile(user, profile)
        stats = await stats_service.get_stats(user)
        await edit_or_send(callback.message, bankroll_message(user, stats), reply_markup=main_menu_keyboard())
        await callback.answer("Профиль риска обновлен")


@router.callback_query(F.data.startswith("signal:"))
async def signal_action(callback: CallbackQuery) -> None:
    _, signal_id_raw, action = callback.data.split(":")
    signal_id = int(signal_id_raw)
    async with get_user_context(callback) as (
        _session,
        _settings,
        user,
        _bankroll_service,
        signal_service,
        stats_service,
    ):
        if action == "pending":
            await callback.answer("Сигнал остается в ожидании")
            return

        signal = await signal_service.signals.get(signal_id)
        if signal is None:
            await callback.answer("Сигнал не найден", show_alert=True)
            return

        if action == "show":
            await edit_or_send(callback.message, signal_message(signal, user.bankroll), reply_markup=signal_keyboard(signal.id))
            await callback.answer()
            return

        if action == "news":
            await edit_or_send(callback.message, signal_news_message(signal), reply_markup=back_to_signal_keyboard(signal.id))
            await callback.answer()
            return

        if action not in {"won", "lost", "void"}:
            await callback.answer("Неизвестное действие", show_alert=True)
            return

        signal = await signal_service.close_signal(user, signal_id, action)
        stats = await stats_service.get_stats(user)
        icon = {"won": "✅", "lost": "❌", "void": "↩️"}[action]
        await edit_or_send(
            callback.message,
            (
                f"{icon} Сигнал закрыт как {action.upper()}\n\n"
                f"Ставка: {money(signal.recommended_stake)} ₽\n"
                f"Кэф: {signal.odds:.2f}\n"
                f"Прибыль: {money(signal.profit)} ₽\n"
                f"Новый банкролл: {money(user.bankroll)} ₽\n"
                f"ROI общий: {stats.roi:+.1f}%"
            ),
            reply_markup=main_menu_keyboard(),
        )
        await callback.answer()


@router.callback_query(F.data.startswith("menu:"))
async def menu_action(callback: CallbackQuery) -> None:
    action = callback.data.split(":", 1)[1]
    async with get_user_context(callback) as (
        _session,
        _settings,
        user,
        _bankroll_service,
        signal_service,
        stats_service,
    ):
        if action == "bankroll":
            await edit_or_send(callback.message, bankroll_message(user, await stats_service.get_stats(user)), reply_markup=main_menu_keyboard())
        elif action == "stats":
            await edit_or_send(callback.message, stats_message(await stats_service.get_stats(user)), reply_markup=main_menu_keyboard())
        elif action == "signals":
            active = await signal_service.list_active_signals()
            if not active:
                await edit_or_send(callback.message, "Активных сигналов пока нет.", reply_markup=main_menu_keyboard())
            else:
                signal = active[0]
                await edit_or_send(callback.message, signal_message(signal, user.bankroll), reply_markup=signal_keyboard(signal.id))
        elif action == "risk":
            await edit_or_send(callback.message, "Выберите профиль риска:", reply_markup=risk_profile_keyboard())
        await callback.answer()


def parse_positive_float(value: str | None) -> float | None:
    if not value:
        return None
    try:
        parsed = float(value.replace(",", ".").strip())
    except ValueError:
        return None
    return parsed if parsed > 0 else None


def parse_positive_int(value: str | None) -> int | None:
    if not value:
        return None
    try:
        parsed = int(value.strip())
    except ValueError:
        return None
    return parsed if parsed > 0 else None


def parse_filters(args: str | None) -> dict[str, str]:
    filters: dict[str, str] = {}
    if not args:
        return filters
    parts = args.split()
    current_key = None
    buffer: list[str] = []
    for part in parts:
        if "=" in part:
            if current_key:
                filters[current_key] = " ".join(buffer)
            current_key, value = part.split("=", 1)
            buffer = [value]
        elif current_key:
            buffer.append(part)
    if current_key:
        filters[current_key] = " ".join(buffer)
    return {key.strip().lower(): value.strip() for key, value in filters.items() if value.strip()}
