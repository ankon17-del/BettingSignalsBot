from collections.abc import Iterable

from app.collectors.odds_collector import OddsSelection
from app.engine.value_detector import bookmaker_probability


def estimate_match_probabilities(*args, **kwargs) -> dict[str, float]:
    event_selection: OddsSelection | None = kwargs.get("event")
    event_selections: Iterable[OddsSelection] = kwargs.get("event_selections") or []

    selections = [selection for selection in event_selections if selection is not None]
    if event_selection is not None and not selections:
        selections = [event_selection]

    market_odds = {selection.market: selection.odds for selection in selections if selection.market and selection.odds > 1.0}

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
        if event_selection is not None:
            base_probability = bookmaker_probability(event_selection.odds)
            if event_selection.market == "Over 2.5":
                over_probability = base_probability
            elif event_selection.market == "Under 2.5":
                over_probability = 1.0 - base_probability
            else:
                over_probability = 0.5
        else:
            over_probability = 0.5
    else:
        over_probability = over_under[0]

    over_probability += _match_shape_adjustment(result_1x2, over_probability)
    over_probability = _clamp(over_probability, 0.35, 0.65)
    under_probability = _clamp(1.0 - over_probability, 0.35, 0.65)

    normalizer = over_probability + under_probability
    if normalizer > 0:
        over_probability /= normalizer
        under_probability /= normalizer

    return {
        "over_2_5": over_probability,
        "under_2_5": under_probability,
    }


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


def _match_shape_adjustment(result_1x2: tuple[float, float, float] | None, current_over_probability: float) -> float:
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


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
