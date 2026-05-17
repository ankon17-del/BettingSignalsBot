from collections import OrderedDict
from datetime import datetime
from zoneinfo import ZoneInfo

from app.collectors.odds_collector import OddsSelection
from app.collectors.news_collector import GNewsSignalInsight
from app.db.models import Signal, User
from app.services.odds_service import OlimpLeagueSummary, OlimpSignalCandidate
from app.services.olimp_signal_service import OlimpGenerationDebugEntry, OlimpGenerationRunResult
from app.services.provider_state import ProviderStatusSnapshot
from app.services.runtime_state import SchedulerStatusSnapshot
from app.services.stats_service import Stats


MOSCOW_TZ = ZoneInfo("Europe/Moscow")


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
    "/debug_olimp_generation — показать, почему рынки дошли или не дошли до draft signal (только админ)\n"
    "  пример: /debug_olimp_generation league=SPL limit=5\n"
    "/generate_olimp_signals — собрать draft value-сигналы по 1/X/2, O/U 2.5 и BTTS (только админ)\n"
    "  пример: /generate_olimp_signals limit=2 league=SPL\n"
    "/show_runtime_config — показать текущие runtime-настройки\n"
    "/show_scheduler_status — показать состояние фонового авто-скана\n\n"
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
    return (
        "\n".join(news_lines)
        if news_lines
        else "- Релевантных новостей не найдено или news-provider временно ограничен."
    )


def signal_message(signal: Signal, bankroll: float) -> str:
    warning = (
        "\n\nВысокий риск, лучше снизить размер или пропустить."
        if signal.risk_level == "high"
        else ""
    )
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


def olimp_generation_debug_message(
    entries: list[OlimpGenerationDebugEntry],
    league_filter: str | None = None,
    limit: int | None = None,
) -> str:
    filter_bits = []
    if league_filter:
        filter_bits.append(f"league={league_filter}")
    if limit is not None:
        filter_bits.append(f"limit={limit}")
    filter_line = f"\nФильтры: {', '.join(filter_bits)}\n" if filter_bits else "\n"

    if not entries:
        return f"По текущей линии OLIMP не нашлось рынков для диагностики.{filter_line}".strip()

    grouped: OrderedDict[str, list[OlimpGenerationDebugEntry]] = OrderedDict()
    for entry in entries:
        selection = entry.selection
        key = selection.source_event_id or f"{selection.match_name}|{selection.league}"
        grouped.setdefault(key, []).append(entry)

    lines = ["🧪 OLIMP generation debug", filter_line.rstrip(), ""]
    for index, items in enumerate(grouped.values(), start=1):
        first = items[0].selection
        kickoff = first.event_start_time.strftime("%Y-%m-%d %H:%M UTC") if first.event_start_time else "n/a"
        lines.append(f"{index}. {first.home_team} — {first.away_team}")
        lines.append(f"Лига: {first.league}")
        lines.append(f"Старт: {kickoff}")
        for entry in items:
            model_part = (
                f" | model {entry.model_probability * 100:.1f}% | value {entry.edge:+.1f}%"
                if entry.model_probability is not None and entry.edge is not None
                else ""
            )
            lines.append(
                f"- {entry.selection.market}: {entry.selection.odds:.2f} | {entry.status}{model_part}\n"
                f"  {entry.reason}"
            )
        lines.append("")

    lines.append(
        "Так видно, где матч отсекся: фильтр лиги, диапазон кэфов, unsupported market, pending, cooldown или value-filter."
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
        detail_lines = []
        if generation.existing_pending_matches > 0:
            detail_lines.append(f"Подходящие матчи уже есть в pending: {generation.existing_pending_matches}.")
        if generation.cooldown_blocked_matches > 0:
            detail_lines.append(f"Матчи под cooldown: {generation.cooldown_blocked_matches}.")
        if detail_lines:
            return (
                "Новых draft value-сигналов не создано."
                f"{filter_line}\n\n"
                + "\n".join(detail_lines)
            )
        return (
            "По текущему draft model stub не найдено value-сигналов."
            f"{filter_line}\n\n"
            "Это ожидаемо: сейчас используется простая временная модель и строгие фильтры по рынкам, лигам и диапазону кэфов."
        )

    lines = [f"✅ Сгенерировано draft signals: {len(generation.created_signals)}"]
    if filter_bits:
        lines.append(f"Фильтры: {', '.join(filter_bits)}")
    lines.extend(
        [
            "",
            f"Матчей прошло базовые фильтры: {generation.passed_filters_matches}",
            f"Уже были в pending: {generation.existing_pending_matches}",
            f"Под cooldown: {generation.cooldown_blocked_matches}",
            "",
            "Пока генерация работает для рынков 1/X/2, Over/Under 2.5 и BTTS через временный model stub.",
        ]
    )
    return "\n".join(lines)


def gnews_debug_message(
    rows: list[tuple[OddsSelection, GNewsSignalInsight]],
    league_filter: str | None = None,
    limit: int | None = None,
) -> str:
    filter_bits = []
    if league_filter:
        filter_bits.append(f"league={league_filter}")
    if limit is not None:
        filter_bits.append(f"limit={limit}")
    filter_line = f"\nФильтры: {', '.join(filter_bits)}\n" if filter_bits else "\n"

    if not rows:
        return f"По текущей линии не нашлось матчей для GNews debug.{filter_line}".strip()

    lines = ["📰 GNews debug", filter_line.rstrip(), ""]
    for index, (selection, insight) in enumerate(rows, start=1):
        kickoff = selection.event_start_time.strftime("%Y-%m-%d %H:%M UTC") if selection.event_start_time else "n/a"
        lines.append(f"{index}. {selection.home_team} — {selection.away_team}")
        lines.append(f"Лига: {selection.league}")
        lines.append(f"Старт: {kickoff}")
        if insight.queries:
            for query_index, query in enumerate(insight.queries, start=1):
                lines.append(f"Q{query_index}: {query}")
        if insight.rate_limited:
            lines.append(f"Статус: rate limited")
            if insight.error_message:
                lines.append(insight.error_message)
        elif not insight.articles:
            lines.append("Статус: новостей не найдено")
        else:
            lines.append(f"Статус: найдено статей {len(insight.articles)}")
            for article in insight.articles[:3]:
                lines.append(
                    f"- {article.source_name} | {article.impact.value}/{article.reliability.value}"
                    f"{' | negative' if article.negative_signal else ''}"
                )
                lines.append(f"  {article.title}")
        lines.append("")
    return "\n".join(lines).strip()


def _format_status_time(value: datetime | None) -> str:
    if value is None:
        return "нет данных"
    localized = value.astimezone(MOSCOW_TZ)
    return localized.strftime("%Y-%m-%d %H:%M:%S MSK")


def scheduler_status_message(status: SchedulerStatusSnapshot) -> str:
    return (
        "⏱️ Scheduler status\n\n"
        f"Configured: {status.configured}\n"
        f"Enabled: {status.enabled}\n"
        f"Interval minutes: {status.interval_minutes or 'n/a'}\n"
        f"Match limit: {status.match_limit or 'n/a'}\n"
        f"Send empty runs: {status.send_empty_runs}\n\n"
        f"Last started: {_format_status_time(status.last_started_at)}\n"
        f"Last finished: {_format_status_time(status.last_finished_at)}\n"
        f"Last result: {status.last_result}\n"
        f"Last message: {status.last_message}\n\n"
        f"Created signals: {status.created_signals}\n"
        f"Passed filters: {status.passed_filters_matches}\n"
        f"Existing pending: {status.existing_pending_matches}\n"
        f"Cooldown blocked: {status.cooldown_blocked_matches}\n"
        f"Last error: {status.last_error or 'нет'}"
    )


def runtime_config_message(settings) -> str:
    priority = ", ".join(settings.olimp_signal_priority_leagues) if settings.olimp_signal_priority_leagues else "не задан"
    allowlist = ", ".join(settings.olimp_signal_league_allowlist) if settings.olimp_signal_league_allowlist else "не задан"
    blocklist = ", ".join(settings.olimp_signal_league_blocklist) if settings.olimp_signal_league_blocklist else "не задан"
    olimp_url = settings.olimp_public_line_url or "не задан"

    return (
        "⚙️ Runtime config\n\n"
        "OLIMP:\n"
        f"Enabled: {settings.olimp_enabled}\n"
        f"Sport: {settings.olimp_sport}\n"
        f"Timeout: {settings.olimp_timeout_seconds}\n"
        f"Line URL: {olimp_url}\n\n"
        "Генерация сигналов:\n"
        f"Priority leagues: {priority}\n"
        f"Allowlist: {allowlist}\n"
        f"Blocklist: {blocklist}\n"
        f"Odds range: {settings.olimp_signal_min_odds:.2f}-{settings.olimp_signal_max_odds:.2f}\n"
        f"Repeat cooldown: {settings.olimp_signal_repeat_cooldown_minutes} min\n"
        f"Won cooldown: {settings.olimp_signal_repeat_cooldown_won_minutes} min\n"
        f"Lost cooldown: {settings.olimp_signal_repeat_cooldown_lost_minutes} min\n"
        f"Void cooldown: {settings.olimp_signal_repeat_cooldown_void_minutes} min\n"
        f"Skipped cooldown: {settings.olimp_signal_repeat_cooldown_skipped_minutes} min\n"
        f"Min minutes before start: {settings.olimp_signal_min_minutes_before_start}\n"
        f"Max hours ahead: {settings.olimp_signal_max_hours_ahead}\n"
        f"Manual max hours ahead: {settings.olimp_manual_max_hours_ahead}\n"
        f"Max signals per run: {settings.olimp_max_signals_per_run}\n\n"
        "Scheduler:\n"
        f"Enabled: {settings.auto_olimp_scan_enabled}\n"
        f"Interval minutes: {settings.auto_olimp_scan_interval_minutes}\n"
        f"Match limit: {settings.auto_olimp_scan_match_limit}\n"
        f"Send empty runs: {settings.auto_olimp_scan_send_empty}"
    )


def thesportsdb_debug_message(
    rows: list[tuple[OddsSelection, object | None, list[str]]],
    league_filter: str | None = None,
    limit: int | None = None,
) -> str:
    filter_bits = []
    if league_filter:
        filter_bits.append(f"league={league_filter}")
    if limit is not None:
        filter_bits.append(f"limit={limit}")
    filter_line = f"\nФильтры: {', '.join(filter_bits)}\n" if filter_bits else "\n"

    if not rows:
        return f"По текущей линии не нашлось матчей для TheSportsDB debug.{filter_line}".strip()

    lines = ["🧭 TheSportsDB debug", filter_line.rstrip(), ""]
    for index, (selection, context, queries) in enumerate(rows, start=1):
        kickoff = selection.event_start_time.strftime("%Y-%m-%d %H:%M UTC") if selection.event_start_time else "n/a"
        lines.append(f"{index}. {selection.home_team} — {selection.away_team}")
        lines.append(f"Лига: {selection.league}")
        lines.append(f"Старт: {kickoff}")
        for query_index, query in enumerate(queries[:4], start=1):
            lines.append(f"Q{query_index}: {query}")

        if context is None:
            lines.append("Статус: match не найден")
        else:
            lines.append("Статус: найден fallback-контекст")
            lines.append(
                f"Home/Away: {getattr(context, 'home_team_name', selection.home_team)} / "
                f"{getattr(context, 'away_team_name', selection.away_team)}"
            )
            lines.append(f"Лига провайдера: {getattr(context, 'league_name', selection.league) or 'n/a'}")
            event_name = getattr(context, "event_name", selection.match_name)
            event_id = getattr(context, "event_id", None)
            lines.append(f"Event: {event_name}{f' | id={event_id}' if event_id else ''}")
        lines.append("")

    lines.append(
        "Этот debug помогает проверить, как TheSportsDB матчит событие и какие официальные названия команд он может отдать как fallback."
    )
    return "\n".join(lines).strip()


def _format_provider_time(value: datetime | None) -> str:
    if value is None:
        return "нет данных"
    localized = value.astimezone(MOSCOW_TZ)
    return localized.strftime("%Y-%m-%d %H:%M:%S MSK")


def provider_status_message(providers: list[ProviderStatusSnapshot]) -> str:
    lines = ["🔌 Provider status", ""]
    for snapshot in providers:
        lines.append(f"{snapshot.name}:")
        lines.append(f"Enabled: {snapshot.enabled}")
        lines.append(f"Configured: {snapshot.configured}")
        lines.append(f"Last status: {snapshot.last_status}")
        lines.append(f"Last attempt: {_format_provider_time(snapshot.last_attempt_at)}")
        lines.append(f"Last success: {_format_provider_time(snapshot.last_success_at)}")
        lines.append(f"Items count: {snapshot.items_count}")
        lines.append(f"Cache hit: {snapshot.cache_hit}")
        if snapshot.cooldown_until is not None:
            lines.append(f"Cooldown until: {_format_provider_time(snapshot.cooldown_until)}")
        lines.append(f"Message: {snapshot.last_message}")
        lines.append(f"Last error: {snapshot.last_error or 'нет'}")
        lines.append("")
    lines.append(
        "Так мы видим, какой провайдер жив, какой упёрся в лимит, а какой просто ещё не использовался после перезапуска."
    )
    return "\n".join(lines).strip()


def runtime_config_message(settings) -> str:
    priority = ", ".join(settings.olimp_signal_priority_leagues) if settings.olimp_signal_priority_leagues else "не задан"
    allowlist = ", ".join(settings.olimp_signal_league_allowlist) if settings.olimp_signal_league_allowlist else "не задан"
    blocklist = ", ".join(settings.olimp_signal_league_blocklist) if settings.olimp_signal_league_blocklist else "не задан"
    olimp_url = settings.olimp_public_line_url or "не задан"

    football_data_ready = settings.football_data_enabled and bool(settings.football_data_api_token)
    api_football_ready = settings.api_football_enabled and bool(settings.api_football_api_key)
    gnews_ready = settings.gnews_enabled and bool(settings.gnews_api_token)
    try:
        from app.collectors.thesportsdb_collector import TheSportsDBCollector

        thesportsdb_ready = TheSportsDBCollector(settings).is_configured
    except Exception:
        thesportsdb_ready = settings.thesportsdb_enabled and bool(settings.thesportsdb_api_key)

    return (
        "⚙️ Runtime config\n\n"
        "OLIMP:\n"
        f"Enabled: {settings.olimp_enabled}\n"
        f"Sport: {settings.olimp_sport}\n"
        f"Timeout: {settings.olimp_timeout_seconds}\n"
        f"Line URL: {olimp_url}\n\n"
        "Football-data:\n"
        f"Enabled: {settings.football_data_enabled}\n"
        f"Configured: {football_data_ready}\n"
        f"Trend window: {settings.football_data_trend_window}\n"
        f"Consider side: {settings.football_data_consider_side}\n"
        f"Name similarity: {settings.football_data_name_similarity:.2f}\n\n"
        "API-FOOTBALL:\n"
        f"Enabled: {settings.api_football_enabled}\n"
        f"Configured: {api_football_ready}\n"
        f"Base URL: {settings.api_football_base_url}\n"
        f"Cache minutes: {settings.api_football_cache_minutes}\n"
        f"Close window minutes: {settings.api_football_close_window_minutes}\n\n"
        "GNews:\n"
        f"Enabled: {settings.gnews_enabled}\n"
        f"Configured: {gnews_ready}\n"
        f"Base URL: {settings.gnews_base_url}\n"
        f"Max articles: {settings.gnews_max_articles}\n"
        f"Lookback hours: {settings.gnews_lookback_hours}\n"
        f"Cache minutes: {settings.gnews_cache_minutes}\n"
        f"Rate limit cooldown: {settings.gnews_rate_limit_cooldown_minutes}\n"
        f"Lang: {settings.gnews_lang or 'any'}\n\n"
        "TheSportsDB:\n"
        f"Enabled: {settings.thesportsdb_enabled}\n"
        f"Configured: {thesportsdb_ready}\n"
        f"Base URL: {settings.thesportsdb_base_url}\n"
        f"Cache minutes: {settings.thesportsdb_cache_minutes}\n"
        f"Rate limit cooldown: {settings.thesportsdb_rate_limit_cooldown_minutes}\n\n"
        "Генерация сигналов:\n"
        f"Priority leagues: {priority}\n"
        f"Allowlist: {allowlist}\n"
        f"Blocklist: {blocklist}\n"
        f"Odds range: {settings.olimp_signal_min_odds:.2f}-{settings.olimp_signal_max_odds:.2f}\n"
        f"Repeat cooldown: {settings.olimp_signal_repeat_cooldown_minutes} min\n"
        f"Won cooldown: {settings.olimp_signal_repeat_cooldown_won_minutes} min\n"
        f"Lost cooldown: {settings.olimp_signal_repeat_cooldown_lost_minutes} min\n"
        f"Void cooldown: {settings.olimp_signal_repeat_cooldown_void_minutes} min\n"
        f"Skipped cooldown: {settings.olimp_signal_repeat_cooldown_skipped_minutes} min\n"
        f"Min minutes before start: {settings.olimp_signal_min_minutes_before_start}\n"
        f"Max hours ahead: {settings.olimp_signal_max_hours_ahead}\n"
        f"Manual max hours ahead: {settings.olimp_manual_max_hours_ahead}\n"
        f"Max signals per run: {settings.olimp_max_signals_per_run}\n\n"
        "Scheduler:\n"
        f"Enabled: {settings.auto_olimp_scan_enabled}\n"
        f"Interval minutes: {settings.auto_olimp_scan_interval_minutes}\n"
        f"Match limit: {settings.auto_olimp_scan_match_limit}\n"
        f"Send empty runs: {settings.auto_olimp_scan_send_empty}"
    )
