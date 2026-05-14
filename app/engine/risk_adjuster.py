def adjust_risk_level(confidence: str, has_negative_news: bool = False) -> str:
    # TODO: combine market volatility, injuries, lineup uncertainty and odds movement.
    if has_negative_news:
        return "high" if confidence == "low" else "medium"
    return "low" if confidence == "high" else "medium"

