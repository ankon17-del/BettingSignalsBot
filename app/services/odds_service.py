from app.collectors.odds_collector import OddsSelection, OlimpOddsCollector
from app.config import Settings


class OddsFeedService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def fetch_olimp_selections(self, limit: int = 12) -> list[OddsSelection]:
        if not self.settings.olimp_enabled:
            raise ValueError("OLIMP feed is disabled in settings.")
        if not self.settings.olimp_public_line_url:
            raise ValueError("OLIMP_PUBLIC_LINE_URL is not configured.")

        collector = OlimpOddsCollector(
            line_url=self.settings.olimp_public_line_url,
            timeout_seconds=self.settings.olimp_timeout_seconds,
            sport=self.settings.olimp_sport,
        )
        selections = await collector.collect()
        selections.sort(
            key=lambda item: (
                item.event_start_time.isoformat() if item.event_start_time else "",
                item.league,
                item.match_name,
                item.market,
            )
        )
        return selections[:limit]
