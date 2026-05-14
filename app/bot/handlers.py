from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message

from app.bot.keyboards import main_menu_keyboard, risk_profile_keyboard, signal_keyboard
from app.bot.messages import HELP, WELCOME, bankroll_message, money, signal_message, stats_message
from app.config import get_settings
from app.db.session import session_context
from app.services.bankroll_service import BankrollService
from app.services.signal_service import SignalService
from app.services.stats_service import StatsService

router = Router()


async def get_user_context(message_or_callback: Message | CallbackQuery):
    settings = get_settings()
    async with session_context() as session:
        tg_user = message_or_callback.from_user
        bankroll_service = BankrollService(session, settings)
        user = await bankroll_service.get_or_create_user(tg_user.id, tg_user.username)
        yield session, settings, user, bankroll_service, SignalService(session), StatsService(session)


@router.message(Command("start"))
async def start(message: Message) -> None:
    async for _context in get_user_context(message):
        await message.answer(WELCOME, reply_markup=main_menu_keyboard())


@router.message(Command("help"))
async def help_command(message: Message) -> None:
    await message.answer(HELP)


@router.message(Command("bankroll"))
async def bankroll(message: Message) -> None:
    async for _session, _settings, user, _bankroll_service, _signal_service, stats_service in get_user_context(message):
        stats = await stats_service.get_stats(user)
        await message.answer(bankroll_message(user, stats), reply_markup=main_menu_keyboard())


@router.message(Command("set_bankroll"))
async def set_bankroll(message: Message, command: CommandObject) -> None:
    amount = parse_positive_float(command.args)
    if amount is None:
        await message.answer("Использование: /set_bankroll 100000")
        return
    async for _session, _settings, user, bankroll_service, _signal_service, _stats_service in get_user_context(message):
        await bankroll_service.set_bankroll(user, amount)
        await message.answer(f"✅ Банкролл обновлён: {money(user.bankroll)} ₽")


@router.message(Command("set_unit"))
async def set_unit(message: Message, command: CommandObject) -> None:
    unit = parse_positive_float(command.args)
    if unit is None or unit > 10:
        await message.answer("Использование: /set_unit 1\nЗначение должно быть больше 0 и не выше 10%.")
        return
    async for _session, _settings, user, bankroll_service, _signal_service, _stats_service in get_user_context(message):
        await bankroll_service.set_unit_percent(user, unit)
        await message.answer(f"✅ Базовый unit обновлён: {user.base_unit_percent:.2f}%")


@router.message(Command("risk_profile"))
async def risk_profile(message: Message) -> None:
    await message.answer("Выберите профиль риска:", reply_markup=risk_profile_keyboard())


@router.message(Command("signals"))
async def signals(message: Message) -> None:
    async for _session, _settings, user, _bankroll_service, signal_service, _stats_service in get_user_context(message):
        active = await signal_service.list_active_signals()
        if not active:
            await message.answer("Активных сигналов пока нет. Админ может создать демо через /add_test_signal.")
            return
        for signal in active:
            await message.answer(signal_message(signal, user.bankroll), reply_markup=signal_keyboard(signal.id))


@router.message(Command("stats"))
async def stats(message: Message, command: CommandObject) -> None:
    filters = parse_filters(command.args)
    async for _session, _settings, user, _bankroll_service, _signal_service, stats_service in get_user_context(message):
        data = await stats_service.get_stats(
            user,
            league=filters.get("league"),
            market=filters.get("market"),
            risk_level=filters.get("risk") or filters.get("risk_level"),
            confidence=filters.get("confidence"),
            month=filters.get("month"),
        )
        await message.answer(stats_message(data))


@router.message(Command("add_test_signal"))
async def add_test_signal(message: Message) -> None:
    async for _session, settings, user, _bankroll_service, signal_service, _stats_service in get_user_context(message):
        if settings.admin_user_id is None or message.from_user.id != settings.admin_user_id:
            await message.answer("⛔ Команда доступна только администратору.")
            return
        signal = await signal_service.create_test_signal(user)
        await message.answer("✅ Демо-сигнал создан")
        await message.answer(signal_message(signal, user.bankroll), reply_markup=signal_keyboard(signal.id))


@router.callback_query(F.data.startswith("risk:"))
async def set_risk_profile(callback: CallbackQuery) -> None:
    profile = callback.data.split(":", 1)[1]
    async for _session, _settings, user, bankroll_service, _signal_service, _stats_service in get_user_context(callback):
        await bankroll_service.set_risk_profile(user, profile)
        await callback.message.answer(f"✅ Профиль риска обновлён: {profile}")
        await callback.answer()


@router.callback_query(F.data.startswith("signal:"))
async def signal_action(callback: CallbackQuery) -> None:
    _, signal_id_raw, action = callback.data.split(":")
    signal_id = int(signal_id_raw)
    async for _session, _settings, user, _bankroll_service, signal_service, stats_service in get_user_context(callback):
        if action == "pending":
            await callback.answer("Сигнал остаётся в ожидании")
            return
        if action == "news":
            signal = await signal_service.signals.get(signal_id)
            if signal is None:
                await callback.answer("Сигнал не найден", show_alert=True)
                return
            text = "\n".join(f"- {link.news_item.title}" for link in signal.news_links) or "Инфополе пока пустое."
            await callback.message.answer(f"📰 Инфополе\n\n{text}")
            await callback.answer()
            return
        if action not in {"won", "lost", "void"}:
            await callback.answer("Неизвестное действие", show_alert=True)
            return
        signal = await signal_service.close_signal(user, signal_id, action)
        if signal is None:
            await callback.answer("Сигнал не найден", show_alert=True)
            return
        stats = await stats_service.get_stats(user)
        await callback.message.answer(
            f"{'✅' if action == 'won' else '❌' if action == 'lost' else '↩️'} Сигнал закрыт как {action.upper()}\n\n"
            f"Ставка: {money(signal.recommended_stake)} ₽\n"
            f"Кэф: {signal.odds:.2f}\n"
            f"Прибыль: {money(signal.profit)} ₽\n"
            f"Новый банкролл: {money(user.bankroll)} ₽\n"
            f"ROI общий: {stats.roi:+.1f}%"
        )
        await callback.answer()


@router.callback_query(F.data.startswith("menu:"))
async def menu_action(callback: CallbackQuery) -> None:
    action = callback.data.split(":", 1)[1]
    async for _session, _settings, user, _bankroll_service, signal_service, stats_service in get_user_context(callback):
        if action == "bankroll":
            await callback.message.answer(bankroll_message(user, await stats_service.get_stats(user)))
        elif action == "stats":
            await callback.message.answer(stats_message(await stats_service.get_stats(user)))
        elif action == "signals":
            active = await signal_service.list_active_signals()
            if not active:
                await callback.message.answer("Активных сигналов пока нет.")
            for signal in active:
                await callback.message.answer(signal_message(signal, user.bankroll), reply_markup=signal_keyboard(signal.id))
        elif action == "risk":
            await callback.message.answer("Выберите профиль риска:", reply_markup=risk_profile_keyboard())
        await callback.answer()


def parse_positive_float(value: str | None) -> float | None:
    if not value:
        return None
    try:
        parsed = float(value.replace(",", ".").strip())
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
