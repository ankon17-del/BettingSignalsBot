from collections.abc import Iterable

from app.collectors.odds_collector import OddsSelection
from app.engine.value_detector import bookmaker_probability


def estimate_match_probabilities(*args, **kwargs) -> dict[str, float]:
    event_selection: OddsSelection | None = kwargs.get("event")
    event_selections: Iterable[OddsSelection] = kwargs.get("event_selections") or []

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

    return {
        "home_win": home_probability,
        "draw": draw_probability,
        "away_win": away_probability,
        "over_2_5": over_probability,
        "under_2_5": under_probability,
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
