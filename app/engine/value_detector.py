def bookmaker_probability(odds: float) -> float:
    return 1 / odds


def value_percent(model_probability: float, odds: float) -> float:
    return (model_probability - bookmaker_probability(odds)) * 100


def is_value_signal(model_probability: float, odds: float, risk_level: str) -> bool:
    book_prob = bookmaker_probability(odds)
    value = (model_probability - book_prob) * 100
    return value >= 5 and model_probability > book_prob and odds >= 1.40 and risk_level != "high"

