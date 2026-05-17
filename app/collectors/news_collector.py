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
_RATE_LIMIT_UNTIL: datetime | None = None


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
    queries: list[str] | None = None
    rate_limited: bool = False
    error_message: str | None = None


class GNewsRateLimitedError(RuntimeError):
    pass


class GNewsCollector:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def is_configured(self) -> bool:
        return self.settings.gnews_enabled and bool(self.settings.gnews_api_token)

    async def fetch_signal_insight(self, selection: OddsSelection) -> GNewsSignalInsight:
        if not self.is_configured:
            return GNewsSignalInsight(articles=[], has_negative_news=False, queries=self._build_queries(selection))

        cache_key = self._cache_key(selection)
        now = datetime.now(UTC)
        global _RATE_LIMIT_UNTIL
        if _RATE_LIMIT_UNTIL is not None and now < _RATE_LIMIT_UNTIL:
            remaining_minutes = max(int((_RATE_LIMIT_UNTIL - now).total_seconds() // 60), 1)
            return GNewsSignalInsight(
                articles=[],
                has_negative_news=False,
                queries=self._build_queries(selection),
                rate_limited=True,
                error_message=f"GNews rate limit active, retry примерно через {remaining_minutes} мин.",
            )
        cache_ttl = timedelta(minutes=max(self.settings.gnews_cache_minutes, 1))
        cached = _NEWS_CACHE.get(cache_key)
        if cached and now - cached[0] <= cache_ttl:
            articles = cached[1]
            return self._build_insight(articles, selection)

        try:
            articles = await self._fetch_articles(selection)
        except GNewsRateLimitedError:
            _RATE_LIMIT_UNTIL = now + timedelta(minutes=max(self.settings.gnews_rate_limit_cooldown_minutes, 1))
            return GNewsSignalInsight(
                articles=[],
                has_negative_news=False,
                queries=self._build_queries(selection),
                rate_limited=True,
                error_message=(
                    f"GNews вернул 429 Too Many Requests. "
                    f"Пауза на {self.settings.gnews_rate_limit_cooldown_minutes} мин."
                ),
            )
        _NEWS_CACHE[cache_key] = (now, articles)
        return self._build_insight(articles, selection)

    async def _fetch_articles(self, selection: OddsSelection) -> list[GNewsArticleSummary]:
        queries = self._build_queries(selection)
        timeout = aiohttp.ClientTimeout(total=self.settings.olimp_timeout_seconds)
        url = f"{self.settings.gnews_base_url.rstrip('/')}/search"
        articles_by_url: dict[str, GNewsArticleSummary] = {}
        async with aiohttp.ClientSession(timeout=timeout, headers={"Accept": "application/json"}) as session:
            for query in queries:
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

                async with session.get(url, params=params) as response:
                    if response.status == 429:
                        raise GNewsRateLimitedError("Too Many Requests")
                    response.raise_for_status()
                    payload = await response.json()

                items = payload.get("articles", []) if isinstance(payload, dict) else []
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    article = self._parse_article(item, selection)
                    if article is None or not article.url:
                        continue
                    articles_by_url.setdefault(article.url, article)
                if articles_by_url:
                    break

        articles = list(articles_by_url.values())
        articles.sort(
            key=lambda item: (
                0 if item.negative_signal else 1,
                0 if item.impact == Impact.high else 1 if item.impact == Impact.medium else 2,
                item.published_at or datetime.min.replace(tzinfo=UTC),
            ),
            reverse=False,
        )
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
        home_tokens = self._team_variants(selection.home_team)
        away_tokens = self._team_variants(selection.away_team)
        if any(token and token in haystack for token in home_tokens):
            matched_team = selection.home_team
        elif any(token and token in haystack for token in away_tokens):
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

    def _build_insight(self, articles: list[GNewsArticleSummary], selection: OddsSelection) -> GNewsSignalInsight:
        if not articles:
            return GNewsSignalInsight(articles=[], has_negative_news=False, queries=self._build_queries(selection))

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
            queries=self._build_queries(selection),
        )

    @staticmethod
    def _cache_key(selection: OddsSelection) -> str:
        return f"{selection.home_team.lower()}|{selection.away_team.lower()}|{selection.league.lower()}"

    @staticmethod
    def _build_query(selection: OddsSelection) -> str:
        return GNewsCollector._build_queries(selection)[0]

    @staticmethod
    def _build_queries(selection: OddsSelection) -> list[str]:
        home_variants = GNewsCollector._team_variants(selection.home_team)
        away_variants = GNewsCollector._team_variants(selection.away_team)
        country = selection.league.split(".", 1)[0].strip() if "." in selection.league else selection.league.strip()

        query_primary = (
            f"(({_quote(home_variants[0])} OR {_quote(home_variants[-1])}) OR "
            f"({_quote(away_variants[0])} OR {_quote(away_variants[-1])})) AND (football OR soccer)"
        )

        queries = [query_primary]
        if country:
            queries.append(f"{query_primary} AND {_quote(country)}")

        translit_home = home_variants[-1]
        translit_away = away_variants[-1]
        if translit_home != selection.home_team.lower() or translit_away != selection.away_team.lower():
            queries.append(
                f"(({_quote(translit_home)} OR {_quote(translit_away)}) AND (football OR soccer))"
            )
        deduped: list[str] = []
        for query in queries:
            if query not in deduped and len(query) <= 200:
                deduped.append(query)
        return deduped or [f"{_quote(selection.home_team)} AND football"]

    @staticmethod
    def _team_variants(team_name: str) -> list[str]:
        normalized = team_name.strip().lower()
        transliterated = normalized.translate(_CYRILLIC_TO_LATIN)
        compact = " ".join(token for token in transliterated.split() if token)
        variants = [normalized]
        if compact and compact not in variants:
            variants.append(compact)
        short = compact.replace(" moskva", "").replace(" almaty", "").replace(" saint ", " st ")
        if short and short not in variants:
            variants.append(short)
        return variants


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


_CYRILLIC_TO_LATIN = str.maketrans(
    {
        "а": "a",
        "б": "b",
        "в": "v",
        "г": "g",
        "д": "d",
        "е": "e",
        "ё": "e",
        "ж": "zh",
        "з": "z",
        "и": "i",
        "й": "i",
        "к": "k",
        "л": "l",
        "м": "m",
        "н": "n",
        "о": "o",
        "п": "p",
        "р": "r",
        "с": "s",
        "т": "t",
        "у": "u",
        "ф": "f",
        "х": "h",
        "ц": "ts",
        "ч": "ch",
        "ш": "sh",
        "щ": "sch",
        "ъ": "",
        "ы": "y",
        "ь": "",
        "э": "e",
        "ю": "yu",
        "я": "ya",
    }
)
