from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import aiohttp

from app.collectors.odds_collector import OddsSelection
from app.db.models import Impact, Reliability
from app.config import Settings


NEGATIVE_KEYWORDS = {
    "injury",
    "injured",
    "out",
    "miss",
    "misses",
    "ruled out",
    "doubt",
    "doubtful",
    "suspension",
    "suspended",
    "absence",
    "setback",
    "hamstring",
    "ankle",
    "knee",
    "lineup concern",
    "without",
    "confirmed out",
}

MEDIUM_KEYWORDS = {
    "lineup",
    "rotation",
    "rested",
    "fitness",
    "training",
    "coach",
    "travel",
    "return",
    "probable",
    "available",
    "uncertain",
    "starter",
    "starting xi",
}

HIGH_RELIABILITY_SOURCES = {
    "reuters",
    "associated press",
    "bbc sport",
    "sky sports",
    "espn",
    "the athletic",
}

_NEWS_CACHE: dict[str, tuple[datetime, list["GNewsArticleSummary"]]] = {}


@dataclass(slots=True)
class GNewsArticleSummary:
    title: str
    description: str | None
    url: str
    source_name: str
    source_url: str | None
    published_at: datetime | None
    matched_team: str | None
    reliability: Reliability
    impact: Impact
    negative_signal: bool


@dataclass(slots=True)
class GNewsSignalInsight:
    articles: list[GNewsArticleSummary]
    has_negative_news: bool
    confidence_shift: int = 0


class GNewsCollector:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def is_configured(self) -> bool:
        return self.settings.gnews_enabled and bool(self.settings.gnews_api_token)

    async def fetch_signal_insight(self, selection: OddsSelection) -> GNewsSignalInsight:
        if not self.is_configured:
            return GNewsSignalInsight(articles=[], has_negative_news=False)

        cache_key = self._cache_key(selection)
        now = datetime.now(UTC)
        cache_ttl = timedelta(minutes=max(self.settings.gnews_cache_minutes, 1))
        cached = _NEWS_CACHE.get(cache_key)
        if cached and now - cached[0] <= cache_ttl:
            articles = cached[1]
            return self._build_insight(articles)

        articles = await self._fetch_articles(selection)
        _NEWS_CACHE[cache_key] = (now, articles)
        return self._build_insight(articles)

    async def _fetch_articles(self, selection: OddsSelection) -> list[GNewsArticleSummary]:
        query = self._build_query(selection)
        params = {
            "q": query,
            "max": str(max(self.settings.gnews_max_articles, 1)),
            "sortby": "publishedAt",
            "in": "title,description",
            "apikey": self.settings.gnews_api_token or "",
            "from": (datetime.now(UTC) - timedelta(hours=max(self.settings.gnews_lookback_hours, 1))).isoformat().replace("+00:00", "Z"),
        }
        if self.settings.gnews_lang:
            params["lang"] = self.settings.gnews_lang

        timeout = aiohttp.ClientTimeout(total=self.settings.olimp_timeout_seconds)
        url = f"{self.settings.gnews_base_url.rstrip('/')}/search"
        async with aiohttp.ClientSession(timeout=timeout, headers={"Accept": "application/json"}) as session:
            async with session.get(url, params=params) as response:
                response.raise_for_status()
                payload = await response.json()

        items = payload.get("articles", []) if isinstance(payload, dict) else []
        articles = [
            article
            for item in items
            if isinstance(item, dict) and (article := self._parse_article(item, selection)) is not None
        ]
        return articles[: max(self.settings.gnews_max_articles, 1)]

    def _parse_article(self, item: dict[str, Any], selection: OddsSelection) -> GNewsArticleSummary | None:
        title = str(item.get("title") or "").strip()
        if not title:
            return None
        description = str(item.get("description") or "").strip() or None
        url = str(item.get("url") or "").strip()
        source = item.get("source") or {}
        source_name = str(source.get("name") or "Unknown source").strip()
        source_url = str(source.get("url") or "").strip() or None
        published_at = _parse_iso_datetime(item.get("publishedAt"))

        matched_team = None
        haystack = f"{title} {description or ''}".lower()
        if selection.home_team.lower() in haystack:
            matched_team = selection.home_team
        elif selection.away_team.lower() in haystack:
            matched_team = selection.away_team

        impact, negative_signal = _classify_impact(title, description)
        reliability = _classify_reliability(source_name)
        return GNewsArticleSummary(
            title=title,
            description=description,
            url=url,
            source_name=source_name,
            source_url=source_url,
            published_at=published_at,
            matched_team=matched_team,
            reliability=reliability,
            impact=impact,
            negative_signal=negative_signal,
        )

    def _build_insight(self, articles: list[GNewsArticleSummary]) -> GNewsSignalInsight:
        if not articles:
            return GNewsSignalInsight(articles=[], has_negative_news=False)

        negative_articles = [article for article in articles if article.negative_signal]
        confidence_shift = 0
        if any(article.impact == Impact.high for article in negative_articles):
            confidence_shift = -1
        elif any(article.impact == Impact.medium for article in negative_articles):
            confidence_shift = -1

        return GNewsSignalInsight(
            articles=articles,
            has_negative_news=bool(negative_articles),
            confidence_shift=confidence_shift,
        )

    @staticmethod
    def _cache_key(selection: OddsSelection) -> str:
        return f"{selection.home_team.lower()}|{selection.away_team.lower()}|{selection.league.lower()}"

    @staticmethod
    def _build_query(selection: OddsSelection) -> str:
        home = _quote(selection.home_team)
        away = _quote(selection.away_team)
        return f"({home} OR {away}) AND (football OR soccer)"


def _classify_reliability(source_name: str) -> Reliability:
    source = source_name.lower().strip()
    if source in HIGH_RELIABILITY_SOURCES:
        return Reliability.high
    if any(token in source for token in {"news", "sport", "football", "soccer"}):
        return Reliability.medium
    return Reliability.low


def _classify_impact(title: str, description: str | None) -> tuple[Impact, bool]:
    haystack = f"{title} {description or ''}".lower()
    if any(token in haystack for token in NEGATIVE_KEYWORDS):
        return Impact.high, True
    if any(token in haystack for token in MEDIUM_KEYWORDS):
        return Impact.medium, False
    return Impact.low, False


def _parse_iso_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def _quote(value: str) -> str:
    escaped = value.replace('"', "")
    return f"\"{escaped}\""

