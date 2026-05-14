from app.db.models import Signal, User
from app.services.stats_service import Stats


def money(value: float) -> str:
    return f"{value:,.0f}".replace(",", " ")


def percent(value: float) -> str:
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.1f}%"


WELCOME = (
    "👋 Betting Signals Bot\n\n"
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
    "/add_test_signal — создать демо-сигнал (только админ)\n\n"
    "Бот не автоматизирует ставки и не подключается к букмекерским аккаунтам."
)


def bankroll_message(user: User, stats: Stats) -> str:
    return (
        "💰 Банкролл\n\n"
        f"Текущий: {money(user.bankroll)} ₽\n"
        f"Начальный: {money(user.initial_bankroll)} ₽\n"
        f"Базовый unit: {user.base_unit_percent:.2f}%\n"
        f"Профиль риска: {user.risk_profile.value}\n"
        f"P/L: {money(stats.profit)} ₽\n"
        f"ROI: {percent(stats.roi)}"
    )


def signal_message(signal: Signal, bankroll: float) -> str:
    warning = "\n\n⚠️ Высокий риск, лучше пропустить или снизить размер." if signal.risk_level == "high" else ""
    news_lines = []
    for link in signal.news_links:
        item = link.news_item
        news_lines.append(f"- {item.title}\n- источник: {item.reliability.value}\n- влияние: {item.impact.value}")
    news = "\n".join(news_lines) if news_lines else "- пока нет новостей"
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
        f"Инфополе:\n{news}\n\n"
        f"Итог:\nVALUE, но с умеренным риском.{warning}"
    )


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

