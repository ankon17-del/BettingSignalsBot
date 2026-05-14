from app.collectors.odds_collector import OddsSelection
from app.db.models import Signal, User
from app.services.stats_service import Stats


def money(value: float) -> str:
    return f"{value:,.0f}".replace(",", " ")


def percent(value: float) -> str:
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.1f}%"


def enum_value(value: object) -> str:
    return getattr(value, "value", str(value))


WELCOME = (
    "Betting Signals Bot\n\n"
    "Бот показывает аналитические value-сигналы и помогает вести банкролл. "
    "Он не делает автоматические ставки, не логинится в аккаунты БК и не обещает прибыль.\n\n"
    "Ставки связаны с финансовым риском. Пользователь всегда принимает решение и ставит вручную."
)

HELP = (
    "Команды:\n"
    "/bankroll — текущий банкролл и риск-настройки\n"
    "/set_bankroll 100000 — установить текущий банкролл\n"
    "/set_unit 1 — установить базовый unit в процентах\n"
    "/risk_profile — выбрать профиль риска\n"
    "/signals — активные сигналы\n"
    "/stats — статистика, можно фильтровать: /stats league=Premier League risk=medium month=2026-05\n"
    "/add_test_signal — создать демо-сигнал (только админ)\n"
    "/fetch_olimp_demo — показать открытую линию OLIMP (только админ)\n\n"
    "Бот не автоматизирует ставки и не подключается к букмекерским аккаунтам."
)


def bankroll_message(user: User, stats: Stats) -> str:
    return (
        "💰 Банкролл\n\n"
        f"Текущий: {money(user.bankroll)} ₽\n"
        f"Начальный: {money(user.initial_bankroll)} ₽\n"
        f"Базовый unit: {user.base_unit_percent:.2f}%\n"
        f"Профиль риска: {enum_value(user.risk_profile)}\n"
        f"P/L: {money(stats.profit)} ₽\n"
        f"ROI: {percent(stats.roi)}"
    )


def signal_news_lines(signal: Signal) -> str:
    news_lines = []
    for link in signal.news_links:
        item = link.news_item
        news_lines.append(
            f"- {item.title}\n- источник: {enum_value(item.reliability)}\n- влияние: {enum_value(item.impact)}"
        )
    return "\n".join(news_lines) if news_lines else "- пока нет новостей"


def signal_message(signal: Signal, bankroll: float) -> str:
    warning = "\n\nВысокий риск, лучше пропустить или снизить размер." if signal.risk_level == "high" else ""
    return (
        "⚽ VALUE SIGNAL\n\n"
        f"Матч: {signal.home_team} — {signal.away_team}\n"
        f"Лига: {signal.league}\n"
        f"Рынок: {signal.market}\n"
        f"Кэф: {signal.odds:.2f}\n\n"
        f"Вероятность БК: {signal.bookmaker_probability * 100:.1f}%\n"
        f"Вероятность модели: {signal.model_probability * 100:.1f}%\n"
        f"Value: {percent(signal.value_percent)}\n\n"
        f"Уверенность: {signal.confidence}\n"
        f"Риск: {signal.risk_level}\n\n"
        f"Банкролл: {money(bankroll)} ₽\n"
        f"Риск от банка: {signal.stake_percent:.2f}%\n"
        f"Рекомендуемая ставка: {money(signal.recommended_stake)} ₽\n\n"
        f"Инфополе:\n{signal_news_lines(signal)}\n\n"
        f"Итог:\nVALUE, но с умеренным риском.{warning}"
    )


def signal_news_message(signal: Signal) -> str:
    return f"📰 Инфополе\n\n{signal_news_lines(signal)}"


def stats_message(stats: Stats) -> str:
    return (
        "📊 Статистика\n\n"
        "Банкролл:\n"
        f"Начальный: {money(stats.initial_bankroll)} ₽\n"
        f"Текущий: {money(stats.current_bankroll)} ₽\n"
        f"P/L: {money(stats.profit)} ₽\n\n"
        "Сигналы:\n"
        f"Всего: {stats.total}\n"
        f"Закрыто: {stats.closed}\n"
        f"Ожидают: {stats.pending}\n\n"
        "Результаты:\n"
        f"Won: {stats.won}\n"
        f"Lost: {stats.lost}\n"
        f"Void: {stats.void}\n\n"
        f"Winrate: {stats.winrate:.1f}%\n"
        f"ROI: {percent(stats.roi)}\n"
        f"Средний кэф: {stats.avg_odds:.2f}\n"
        f"Средний value: {percent(stats.avg_value)}\n"
        f"Max drawdown: {percent(stats.max_drawdown)}"
    )


def olimp_selection_line(selection: OddsSelection) -> str:
    kickoff = ""
    if selection.event_start_time is not None:
        kickoff = f"\nСтарт: {selection.event_start_time.strftime('%Y-%m-%d %H:%M UTC')}"
    return (
        f"{selection.home_team} — {selection.away_team}\n"
        f"Лига: {selection.league}\n"
        f"Рынок: {selection.market}\n"
        f"Кэф OLIMP: {selection.odds:.2f}{kickoff}"
    )


def olimp_digest_message(selections: list[OddsSelection]) -> str:
    if not selections:
        return "По публичной линии OLIMP пока не найдено подходящих prematch-рынков."

    lines = ["📡 OLIMP line demo", ""]
    for index, selection in enumerate(selections, start=1):
        lines.append(f"{index}. {olimp_selection_line(selection)}")
        lines.append("")
    lines.append("Это демонстрация открытой линии OLIMP без логина и без автоставок.")
    return "\n".join(lines).strip()
