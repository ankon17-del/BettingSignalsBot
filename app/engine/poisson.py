from collections.abc import Iterable

from app.collectors.api_football_collector import ApiFootballFixtureContext
from app.collectors.odds_collector import OddsSelection
from app.collectors.stats_collector import MatchTrendSnapshot
from app.engine.value_detector import bookmaker_probability


def estimate_match_probabilities(*args, **kwargs) -> dict[str, float]:
    event_selection: OddsSelection | None = kwargs.get("event")
    event_selections: Iterable[OddsSelection] = kwargs.get("event_selections") or []
    trend_snapshot: MatchTrendSnapshot | None = kwargs.get("trend_snapshot")
    api_football_context: ApiFootballFixtureContext | None = kwargs.get("api_football_context")

    selections = [selection for selection in event_selections if selection is not None]
    if event_selection is not None and not selections:
        selections = [event_selection]

    market_odds = {
        selection.market: selection.odds
        for selection in selections
        if selection.market and selection.odds and selection.odds > 1.0
    }

    over_under = _normalized_market_pair(
        market_odds.get("Over 2.5"),
        market_odds.get("Under 2.5"),
    )
    result_1x2 = _normalized_1x2(
        market_odds.get("1"),
        market_odds.get("X"),
        market_odds.get("2"),
    )

    if over_under is None:
        over_probability = _fallback_total_probability(event_selection)
    else:
        over_probability = over_under[0]

    over_probability += _totals_shape_adjustment(result_1x2, over_probability)
    over_probability = _clamp(over_probability, 0.35, 0.65)
    under_probability = _clamp(1.0 - over_probability, 0.35, 0.65)
    over_probability, under_probability = _renormalize_pair(over_probability, under_probability)

    home_probability, draw_probability, away_probability = _resolve_1x2_probabilities(
        result_1x2=result_1x2,
        over_probability=over_probability,
        under_probability=under_probability,
    )
    btts_yes_probability, btts_no_probability = _resolve_btts_probabilities(
        home_probability=home_probability,
        draw_probability=draw_probability,
        away_probability=away_probability,
        over_probability=over_probability,
        under_probability=under_probability,
    )

    if trend_snapshot is not None:
        over_probability, under_probability = _blend_totals_with_trend(
            over_probability=over_probability,
            under_probability=under_probability,
            trend_snapshot=trend_snapshot,
        )
        home_probability, draw_probability, away_probability = _blend_1x2_with_trend(
            home_probability=home_probability,
            draw_probability=draw_probability,
            away_probability=away_probability,
            over_probability=over_probability,
            under_probability=under_probability,
            trend_snapshot=trend_snapshot,
        )
        btts_yes_probability, btts_no_probability = _blend_btts_with_trend(
            btts_yes_probability=btts_yes_probability,
            btts_no_probability=btts_no_probability,
            home_probability=home_probability,
            away_probability=away_probability,
            trend_snapshot=trend_snapshot,
        )

    if api_football_context is not None:
        home_probability, draw_probability, away_probability = _blend_1x2_with_api_football(
            home_probability=home_probability,
            draw_probability=draw_probability,
            away_probability=away_probability,
            api_football_context=api_football_context,
        )
        over_probability, under_probability = _blend_totals_with_api_football(
            over_probability=over_probability,
            under_probability=under_probability,
            api_football_context=api_football_context,
        )
        btts_yes_probability, btts_no_probability = _blend_btts_with_api_football(
            btts_yes_probability=btts_yes_probability,
            btts_no_probability=btts_no_probability,
            api_football_context=api_football_context,
        )

    return {
        "home_win": home_probability,
        "draw": draw_probability,
        "away_win": away_probability,
        "over_2_5": over_probability,
        "under_2_5": under_probability,
        "btts_yes": btts_yes_probability,
        "btts_no": btts_no_probability,
    }


def _fallback_total_probability(event_selection: OddsSelection | None) -> float:
    if event_selection is None:
        return 0.5
    base_probability = bookmaker_probability(event_selection.odds)
    if event_selection.market == "Over 2.5":
        return base_probability
    if event_selection.market == "Under 2.5":
        return 1.0 - base_probability
    return 0.5


def _normalized_market_pair(first_odds: float | None, second_odds: float | None) -> tuple[float, float] | None:
    if not first_odds or not second_odds:
        return None
    first_probability = bookmaker_probability(first_odds)
    second_probability = bookmaker_probability(second_odds)
    total = first_probability + second_probability
    if total <= 0:
        return None
    return first_probability / total, second_probability / total


def _normalized_1x2(
    home_odds: float | None,
    draw_odds: float | None,
    away_odds: float | None,
) -> tuple[float, float, float] | None:
    if not home_odds or not draw_odds or not away_odds:
        return None
    home_probability = bookmaker_probability(home_odds)
    draw_probability = bookmaker_probability(draw_odds)
    away_probability = bookmaker_probability(away_odds)
    total = home_probability + draw_probability + away_probability
    if total <= 0:
        return None
    return (
        home_probability / total,
        draw_probability / total,
        away_probability / total,
    )


def _totals_shape_adjustment(result_1x2: tuple[float, float, float] | None, current_over_probability: float) -> float:
    if result_1x2 is None:
        return _totals_price_adjustment_only(current_over_probability)

    home_probability, draw_probability, away_probability = result_1x2
    favorite_gap = abs(home_probability - away_probability)
    adjustment = _totals_price_adjustment_only(current_over_probability)

    if favorite_gap >= 0.22:
        adjustment -= 0.025
    elif favorite_gap <= 0.08:
        adjustment += 0.020

    if draw_probability >= 0.29:
        adjustment -= 0.015
    elif draw_probability <= 0.23:
        adjustment += 0.015

    decisive_probability = home_probability + away_probability
    if decisive_probability >= 0.78:
        adjustment += 0.010

    return adjustment


def _totals_price_adjustment_only(current_over_probability: float) -> float:
    if current_over_probability >= 0.60:
        return -0.010
    if current_over_probability <= 0.40:
        return 0.010
    if 0.47 <= current_over_probability <= 0.53:
        return 0.010
    return 0.0


def _resolve_1x2_probabilities(
    result_1x2: tuple[float, float, float] | None,
    over_probability: float,
    under_probability: float,
) -> tuple[float, float, float]:
    if result_1x2 is None:
        return _fallback_1x2_from_totals(over_probability, under_probability)

    home_probability, draw_probability, away_probability = result_1x2

    draw_adjustment = 0.0
    if over_probability >= 0.56:
        draw_adjustment -= 0.020
    elif under_probability >= 0.56:
        draw_adjustment += 0.020
    elif 0.49 <= over_probability <= 0.53:
        draw_adjustment += 0.005

    adjusted_draw = _clamp(draw_probability + draw_adjustment, 0.18, 0.36)
    decisive_before = max(home_probability + away_probability, 0.01)
    decisive_after = max(1.0 - adjusted_draw, 0.01)
    scale = decisive_after / decisive_before
    adjusted_home = home_probability * scale
    adjusted_away = away_probability * scale
    return _renormalize_triplet(adjusted_home, adjusted_draw, adjusted_away)


def _fallback_1x2_from_totals(over_probability: float, under_probability: float) -> tuple[float, float, float]:
    draw_probability = _clamp(0.30 + (under_probability - over_probability) * 0.12, 0.24, 0.34)
    decisive_probability = 1.0 - draw_probability
    home_probability = decisive_probability * 0.51
    away_probability = decisive_probability * 0.49
    return _renormalize_triplet(home_probability, draw_probability, away_probability)


def _resolve_btts_probabilities(
    home_probability: float,
    draw_probability: float,
    away_probability: float,
    over_probability: float,
    under_probability: float,
) -> tuple[float, float]:
    favorite_gap = abs(home_probability - away_probability)
    btts_yes_probability = 0.50
    btts_yes_probability += (over_probability - 0.50) * 0.70
    btts_yes_probability -= max(favorite_gap - 0.10, 0.0) * 0.28
    btts_yes_probability -= max(draw_probability - 0.30, 0.0) * 0.08
    btts_yes_probability += max(min(home_probability, away_probability) - 0.23, 0.0) * 0.18
    btts_yes_probability = _clamp(btts_yes_probability, 0.36, 0.66)
    btts_no_probability = _clamp(1.0 - btts_yes_probability, 0.34, 0.64)
    return _renormalize_pair(btts_yes_probability, btts_no_probability)


def _blend_totals_with_trend(
    over_probability: float,
    under_probability: float,
    trend_snapshot: MatchTrendSnapshot,
) -> tuple[float, float]:
    trend_values: list[float] = []

    pct_over = _average_present(
        trend_snapshot.home_team.pct_o_25,
        trend_snapshot.away_team.pct_o_25,
    )
    if pct_over is not None:
        trend_values.append(_clamp(pct_over, 0.20, 0.80))

    expected_home_goals = _expected_side_goals(
        trend_snapshot.home_team.avg_goals_scored,
        trend_snapshot.away_team.avg_goals_conceded,
    )
    expected_away_goals = _expected_side_goals(
        trend_snapshot.away_team.avg_goals_scored,
        trend_snapshot.home_team.avg_goals_conceded,
    )
    if expected_home_goals is not None and expected_away_goals is not None:
        expected_total = expected_home_goals + expected_away_goals
        trend_values.append(_clamp(0.50 + (expected_total - 2.55) * 0.18, 0.28, 0.72))

    if not trend_values:
        return over_probability, under_probability

    trend_over = sum(trend_values) / len(trend_values)
    blended_over = _clamp(over_probability * 0.62 + trend_over * 0.38, 0.30, 0.70)
    blended_under = _clamp(1.0 - blended_over, 0.30, 0.70)
    return _renormalize_pair(blended_over, blended_under)


def _blend_1x2_with_trend(
    home_probability: float,
    draw_probability: float,
    away_probability: float,
    over_probability: float,
    under_probability: float,
    trend_snapshot: MatchTrendSnapshot,
) -> tuple[float, float, float]:
    home_strength = _trend_strength_score(
        avg_points=trend_snapshot.home_team.avg_points,
        pct_wins=trend_snapshot.home_team.pct_wins,
        pct_losses=trend_snapshot.home_team.pct_losses,
        avg_goals_scored=trend_snapshot.home_team.avg_goals_scored,
        avg_goals_conceded=trend_snapshot.home_team.avg_goals_conceded,
    )
    away_strength = _trend_strength_score(
        avg_points=trend_snapshot.away_team.avg_points,
        pct_wins=trend_snapshot.away_team.pct_wins,
        pct_losses=trend_snapshot.away_team.pct_losses,
        avg_goals_scored=trend_snapshot.away_team.avg_goals_scored,
        avg_goals_conceded=trend_snapshot.away_team.avg_goals_conceded,
    )
    if home_strength is None or away_strength is None:
        return home_probability, draw_probability, away_probability

    gap = home_strength - away_strength
    draw_trend = _average_present(
        trend_snapshot.home_team.pct_draws,
        trend_snapshot.away_team.pct_draws,
    )

    trend_home = home_probability + gap * 0.035
    trend_away = away_probability - gap * 0.035
    trend_draw = draw_probability + ((draw_trend or draw_probability) - draw_probability) * 0.55
    trend_draw += (under_probability - over_probability) * 0.025

    trend_home, trend_draw, trend_away = _renormalize_triplet(
        _clamp(trend_home, 0.15, 0.72),
        _clamp(trend_draw, 0.16, 0.40),
        _clamp(trend_away, 0.15, 0.72),
    )
    blended_home, blended_draw, blended_away = _renormalize_triplet(
        home_probability * 0.68 + trend_home * 0.32,
        draw_probability * 0.68 + trend_draw * 0.32,
        away_probability * 0.68 + trend_away * 0.32,
    )
    return blended_home, blended_draw, blended_away


def _blend_btts_with_trend(
    btts_yes_probability: float,
    btts_no_probability: float,
    home_probability: float,
    away_probability: float,
    trend_snapshot: MatchTrendSnapshot,
) -> tuple[float, float]:
    trend_values: list[float] = []

    pct_btts = _average_present(
        trend_snapshot.home_team.pct_bts,
        trend_snapshot.away_team.pct_bts,
    )
    if pct_btts is not None:
        trend_values.append(_clamp(pct_btts, 0.22, 0.78))

    expected_home_goals = _expected_side_goals(
        trend_snapshot.home_team.avg_goals_scored,
        trend_snapshot.away_team.avg_goals_conceded,
    )
    expected_away_goals = _expected_side_goals(
        trend_snapshot.away_team.avg_goals_scored,
        trend_snapshot.home_team.avg_goals_conceded,
    )
    if expected_home_goals is not None and expected_away_goals is not None:
        weaker_attack = min(expected_home_goals, expected_away_goals)
        trend_values.append(_clamp(0.42 + (weaker_attack - 0.85) * 0.30, 0.26, 0.74))

    if not trend_values:
        return btts_yes_probability, btts_no_probability

    favorite_gap = abs(home_probability - away_probability)
    trend_yes = sum(trend_values) / len(trend_values)
    trend_yes -= max(favorite_gap - 0.14, 0.0) * 0.20
    trend_yes = _clamp(trend_yes, 0.24, 0.76)
    blended_yes = _clamp(btts_yes_probability * 0.60 + trend_yes * 0.40, 0.24, 0.76)
    blended_no = _clamp(1.0 - blended_yes, 0.24, 0.76)
    return _renormalize_pair(blended_yes, blended_no)


def _blend_1x2_with_api_football(
    home_probability: float,
    draw_probability: float,
    away_probability: float,
    api_football_context: ApiFootballFixtureContext,
) -> tuple[float, float, float]:
    injury_gap = api_football_context.home_injuries - api_football_context.away_injuries
    shift = _clamp(injury_gap * 0.012, -0.045, 0.045)
    adjusted_home = home_probability - shift
    adjusted_away = away_probability + shift
    adjusted_draw = draw_probability

    if api_football_context.lineups_confirmed:
        adjusted_draw -= 0.006
        decisive_total = max(adjusted_home + adjusted_away, 0.01)
        scale = max(1.0 - adjusted_draw, 0.01) / decisive_total
        adjusted_home *= scale
        adjusted_away *= scale

    return _renormalize_triplet(
        _clamp(adjusted_home, 0.12, 0.78),
        _clamp(adjusted_draw, 0.14, 0.42),
        _clamp(adjusted_away, 0.12, 0.78),
    )


def _blend_totals_with_api_football(
    over_probability: float,
    under_probability: float,
    api_football_context: ApiFootballFixtureContext,
) -> tuple[float, float]:
    total_injuries = api_football_context.home_injuries + api_football_context.away_injuries
    injury_drag = min(total_injuries, 6) * 0.006
    over_adjusted = over_probability - injury_drag

    if api_football_context.lineups_confirmed:
        over_adjusted += 0.010

    over_adjusted = _clamp(over_adjusted, 0.28, 0.72)
    under_adjusted = _clamp(1.0 - over_adjusted, 0.28, 0.72)
    return _renormalize_pair(over_adjusted, under_adjusted)


def _blend_btts_with_api_football(
    btts_yes_probability: float,
    btts_no_probability: float,
    api_football_context: ApiFootballFixtureContext,
) -> tuple[float, float]:
    injury_gap = abs(api_football_context.home_injuries - api_football_context.away_injuries)
    total_injuries = api_football_context.home_injuries + api_football_context.away_injuries

    yes_adjusted = btts_yes_probability
    yes_adjusted -= min(injury_gap, 4) * 0.010
    yes_adjusted -= min(total_injuries, 6) * 0.004
    if api_football_context.lineups_confirmed:
        yes_adjusted += 0.008

    yes_adjusted = _clamp(yes_adjusted, 0.22, 0.78)
    no_adjusted = _clamp(1.0 - yes_adjusted, 0.22, 0.78)
    return _renormalize_pair(yes_adjusted, no_adjusted)


def _renormalize_pair(first: float, second: float) -> tuple[float, float]:
    total = first + second
    if total <= 0:
        return 0.5, 0.5
    return first / total, second / total


def _renormalize_triplet(first: float, second: float, third: float) -> tuple[float, float, float]:
    total = first + second + third
    if total <= 0:
        return 0.34, 0.32, 0.34
    return first / total, second / total, third / total


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _average_present(*values: float | None) -> float | None:
    present = [value for value in values if value is not None]
    if not present:
        return None
    return sum(present) / len(present)


def _expected_side_goals(avg_scored: float | None, avg_conceded_opponent: float | None) -> float | None:
    if avg_scored is None and avg_conceded_opponent is None:
        return None
    if avg_scored is None:
        return avg_conceded_opponent
    if avg_conceded_opponent is None:
        return avg_scored
    return (avg_scored + avg_conceded_opponent) / 2


def _trend_strength_score(
    avg_points: float | None,
    pct_wins: float | None,
    pct_losses: float | None,
    avg_goals_scored: float | None,
    avg_goals_conceded: float | None,
) -> float | None:
    if all(value is None for value in (avg_points, pct_wins, pct_losses, avg_goals_scored, avg_goals_conceded)):
        return None
    return (
        (avg_points or 1.5) * 0.45
        + (pct_wins or 0.33) * 0.80
        - (pct_losses or 0.33) * 0.45
        + (avg_goals_scored or 1.2) * 0.22
        - (avg_goals_conceded or 1.2) * 0.16
    )
