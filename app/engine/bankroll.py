RISK_MATRIX = {
    "conservative": {"weak": 0.25, "normal": 0.5, "strong": 1.0},
    "normal": {"weak": 0.5, "normal": 1.0, "strong": 1.5},
    "aggressive": {"weak": 1.0, "normal": 2.0, "strong": 3.0},
}


def classify_signal_strength(value_percent: float) -> str:
    if value_percent >= 8:
        return "strong"
    if value_percent >= 5:
        return "normal"
    return "weak"


def get_stake_percent(risk_profile: str, value_percent: float, risk_level: str, base_unit_percent: float) -> float:
    if risk_level == "high":
        return min(base_unit_percent * 0.5, 0.5)
    strength = classify_signal_strength(value_percent)
    return RISK_MATRIX.get(risk_profile, RISK_MATRIX["normal"])[strength]


def calculate_recommended_stake(bankroll: float, stake_percent: float) -> float:
    return round(bankroll * stake_percent / 100, 2)


def calculate_profit(status: str, stake: float, odds: float) -> float:
    if status == "won":
        return round(stake * (odds - 1), 2)
    if status == "lost":
        return round(-stake, 2)
    return 0.0

