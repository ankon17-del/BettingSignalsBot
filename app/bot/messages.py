from collections import OrderedDict

from app.collectors.odds_collector import OddsSelection
from app.db.models import Signal, User
from app.services.odds_service import OlimpLeagueSummary, OlimpSignalCandidate
from app.services.olimp_signal_service import OlimpGenerationRunResult
from app.services.stats_service import Stats


def money(value: float) -> str:
    return f"{value:,.0f}".replace(",", " ")


def percent(value: float) -> str:
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.1f}%"


def enum_value(value: object) -> str:
    return getattr(value, "value", str(value))


def risk_summary_text(risk_level: str) -> str:
    mapping = {
        "low": "VALUE, риск низкий.",
        "medium": "VALUE, но риск умеренный.",
        "high": "VALUE, но риск высокий. Лучше снизить размер или пропустить.",
    }
    return mapping.get(risk_level, "VALUE-сценарий требует ручной оценки.")


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
    "/fetch_olimp_demo — показать shortlist открытой линии OLIMP (только админ)\n"
    "  пример: /fetch_olimp_demo league=SPL limit=3\n"
    "/fetch_olimp_candidates — показать кандидатов для value engine (только админ)\n"
    "  пример: /fetch_olimp_candidates league=SPL limit=3\n"
    "/fetch_olimp_leagues — показать доступные лиги OLIMP (только админ)\n"
    "  пример: /fetch_olimp_leagues query=Россия limit=10\n"
    "/generate_olimp_signals — собрать draft value-сигналы по O/U 2.5 (только админ)\n"
    "  пример: /generate_olimp_signals limit=2 league=SPL\n\n"
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
    for link in signal.__dict__.get("news_links") or []:
        item = link.news_item
        news_lines.append(
            f"- {item.title}\n- источник: {enum_value(item.reliability)}\n- влияние: {enum_value(item.impact)}"
        )
    return "\n".join(news_lines) if news_lines else "- пока нет новостей"


def signal_message(signal: Signal, bankroll: float) -> str:
    warning = "\n\nВысокий риск, лучше снизить размер или пропустить." if signal.risk_level == "high" else ""
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
        f"Итог:\n{risk_summary_text(signal.risk_level)}{warning}"
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


def olimp_digest_message(selections: list[OddsSelection]) -> str:
    grouped: OrderedDict[str, list[OddsSelection]] = OrderedDict()
    for selection in selections:
        key = selection.source_event_id or f"{selection.match_name}|{selection.league}"
        grouped.setdefault(key, []).append(selection)

    lines = ["📡 OLIMP shortlist", ""]
    for index, items in enumerate(grouped.values(), start=1):
        first = items[0]
        market_line = " | ".join(f"{item.market}: {item.odds:.2f}" for item in items)
        kickoff = first.event_start_time.strftime("%Y-%m-%d %H:%M UTC") if first.event_start_time else "n/a"
        lines.append(f"{index}. {first.home_team} — {first.away_team}")
        lines.append(f"Лига: {first.league}")
        lines.append(f"Старт: {kickoff}")
        lines.append(f"Рынки: {market_line}")
        lines.append("")

    lines.append("Это shortlist открытой линии OLIMP для следующих value-кандидатов.")
    return "\n".join(lines).strip()


def olimp_digest_summary_message(
    selections: list[OddsSelection],
    league_filter: str | None = None,
    match_limit: int | None = None,
) -> str:
    if selections:
        return olimp_digest_message(selections)

    filter_bits = []
    if match_limit is not None:
        filter_bits.append(f"limit={match_limit}")
    if league_filter:
        filter_bits.append(f"league={league_filter}")
    filter_line = f"\nФильтры: {', '.join(filter_bits)}" if filter_bits else ""
    return f"По публичной линии OLIMP не найдено подходящих prematch-рынков.{filter_line}"


def olimp_candidates_message(candidates: list[OlimpSignalCandidate]) -> str:
    grouped: OrderedDict[str, list[OlimpSignalCandidate]] = OrderedDict()
    for candidate in candidates:
        selection = candidate.selection
        key = selection.source_event_id or f"{selection.match_name}|{selection.league}"
        grouped.setdefault(key, []).append(candidate)

    lines = ["🎯 OLIMP candidates", ""]
    for index, items in enumerate(grouped.values(), start=1):
        first = items[0].selection
        kickoff = first.event_start_time.strftime("%Y-%m-%d %H:%M UTC") if first.event_start_time else "n/a"
        lines.append(f"{index}. {first.home_team} — {first.away_team}")
        lines.append(f"Лига: {first.league}")
        lines.append(f"Старт: {kickoff}")
        for candidate in items:
            selection = candidate.selection
            lines.append(
                f"- {selection.market}: {selection.odds:.2f} | "
                f"БК {candidate.bookmaker_probability * 100:.1f}% | "
                f"{candidate.candidate_tier}"
            )
        lines.append(f"Причина: {items[0].rationale}")
        lines.append("")

    lines.append("Это ещё не value-сигналы: здесь только рынки, которые стоит подать в модель.")
    return "\n".join(lines).strip()


def olimp_candidates_summary_message(
    candidates: list[OlimpSignalCandidate],
    league_filter: str | None = None,
    match_limit: int | None = None,
) -> str:
    if candidates:
        return olimp_candidates_message(candidates)

    filter_bits = []
    if match_limit is not None:
        filter_bits.append(f"limit={match_limit}")
    if league_filter:
        filter_bits.append(f"league={league_filter}")
    filter_line = f"\nФильтры: {', '.join(filter_bits)}" if filter_bits else ""
    return f"По линии OLIMP пока не найдено кандидатов под текущие фильтры.{filter_line}"


def olimp_leagues_message(
    leagues: list[OlimpLeagueSummary],
    query: str | None = None,
    limit: int | None = None,
) -> str:
    filter_bits = []
    if query:
        filter_bits.append(f"query={query}")
    if limit is not None:
        filter_bits.append(f"limit={limit}")
    filter_line = f"\nФильтры: {', '.join(filter_bits)}\n" if filter_bits else "\n"

    if not leagues:
        return f"По открытой линии OLIMP не найдено лиг.{filter_line}".strip()

    lines = ["🏷️ OLIMP leagues", filter_line.rstrip(), ""]
    for index, item in enumerate(leagues, start=1):
        lines.append(f"{index}. {item.league} — матчей: {item.matches_count}")
    lines.extend(
        [
            "",
            "Эти названия можно использовать в фильтрах league=... для shortlist, candidates и draft signals.",
        ]
    )
    return "\n".join(lines).strip()


def olimp_generation_summary(
    generation: OlimpGenerationRunResult,
    create_limit: int | None = None,
    league_filter: str | None = None,
) -> str:
    filter_bits = []
    if create_limit is not None:
        filter_bits.append(f"limit={create_limit}")
    if league_filter:
        filter_bits.append(f"league={league_filter}")
    filter_line = f"\nФильтры: {', '.join(filter_bits)}" if filter_bits else ""

    if not generation.created_signals:
        if generation.existing_pending_matches > 0:
            return (
                "Новых draft value-сигналов не создано."
                f"{filter_line}\n\n"
                f"Подходящие матчи уже есть в pending: {generation.existing_pending_matches}.\n"
                "Сначала закрой или пропусти старые сигналы, если хочешь пересобрать новые по тем же матчам."
            )
        return (
            "По текущему O/U 2.5 stub не найдено draft value-сигналов."
            f"{filter_line}\n\n"
            "Это ожидаемо: сейчас используется простая временная модель и строгие фильтры по рынкам, лигам и диапазону кэфов."
        )

    lines = [
        f"✅ Сгенерировано draft signals: {len(generation.created_signals)}",
    ]
    if filter_bits:
        lines.append(f"Фильтры: {', '.join(filter_bits)}")
    lines.extend(
        [
            "",
            f"Матчей прошло базовые фильтры: {generation.passed_filters_matches}",
            f"Уже были в pending: {generation.existing_pending_matches}",
            "",
            "Пока генерация работает только для рынка Over/Under 2.5 через временный model stub.",
        ]
    )
    return "\n".join(lines)
