from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    bot_token: str = Field(alias="BOT_TOKEN")
    database_url: str = Field(alias="DATABASE_URL")
    admin_user_id: int | None = Field(default=None, alias="ADMIN_USER_ID")
    default_bankroll: float = Field(default=10000, alias="DEFAULT_BANKROLL")
    default_risk_profile: str = Field(default="normal", alias="DEFAULT_RISK_PROFILE")
    default_unit_percent: float = Field(default=1.0, alias="DEFAULT_UNIT_PERCENT")
    olimp_enabled: bool = Field(default=False, alias="OLIMP_ENABLED")
    olimp_public_line_url: str | None = Field(default=None, alias="OLIMP_PUBLIC_LINE_URL")
    olimp_timeout_seconds: float = Field(default=10.0, alias="OLIMP_TIMEOUT_SECONDS")
    olimp_sport: str = Field(default="football", alias="OLIMP_SPORT")
    olimp_signal_priority_leagues_raw: str = Field(default="", alias="OLIMP_SIGNAL_PRIORITY_LEAGUES")
    olimp_signal_league_allowlist_raw: str = Field(default="", alias="OLIMP_SIGNAL_LEAGUE_ALLOWLIST")
    olimp_signal_league_blocklist_raw: str = Field(default="", alias="OLIMP_SIGNAL_LEAGUE_BLOCKLIST")
    olimp_max_signals_per_run: int = Field(default=3, alias="OLIMP_MAX_SIGNALS_PER_RUN")
    olimp_signal_min_odds: float = Field(default=1.75, alias="OLIMP_SIGNAL_MIN_ODDS")
    olimp_signal_max_odds: float = Field(default=2.40, alias="OLIMP_SIGNAL_MAX_ODDS")
    olimp_signal_repeat_cooldown_minutes: int = Field(default=120, alias="OLIMP_SIGNAL_REPEAT_COOLDOWN_MINUTES")
    olimp_signal_repeat_cooldown_won_minutes: int = Field(default=180, alias="OLIMP_SIGNAL_REPEAT_COOLDOWN_WON_MINUTES")
    olimp_signal_repeat_cooldown_lost_minutes: int = Field(default=180, alias="OLIMP_SIGNAL_REPEAT_COOLDOWN_LOST_MINUTES")
    olimp_signal_repeat_cooldown_void_minutes: int = Field(default=45, alias="OLIMP_SIGNAL_REPEAT_COOLDOWN_VOID_MINUTES")
    olimp_signal_repeat_cooldown_skipped_minutes: int = Field(default=90, alias="OLIMP_SIGNAL_REPEAT_COOLDOWN_SKIPPED_MINUTES")
    olimp_signal_min_minutes_before_start: int = Field(default=15, alias="OLIMP_SIGNAL_MIN_MINUTES_BEFORE_START")
    olimp_signal_max_hours_ahead: int = Field(default=6, alias="OLIMP_SIGNAL_MAX_HOURS_AHEAD")
    football_data_enabled: bool = Field(default=False, alias="FOOTBALL_DATA_ENABLED")
    football_data_api_token: str | None = Field(default=None, alias="FOOTBALL_DATA_API_TOKEN")
    football_data_base_url: str = Field(default="https://api.football-data.org/v4", alias="FOOTBALL_DATA_BASE_URL")
    football_data_trend_window: int = Field(default=5, alias="FOOTBALL_DATA_TREND_WINDOW")
    football_data_consider_side: bool = Field(default=True, alias="FOOTBALL_DATA_CONSIDER_SIDE")
    football_data_name_similarity: float = Field(default=0.72, alias="FOOTBALL_DATA_NAME_SIMILARITY")
    api_football_enabled: bool = Field(default=False, alias="API_FOOTBALL_ENABLED")
    api_football_api_key: str | None = Field(default=None, alias="API_FOOTBALL_API_KEY")
    api_football_base_url: str = Field(default="https://v3.football.api-sports.io", alias="API_FOOTBALL_BASE_URL")
    api_football_cache_minutes: int = Field(default=20, alias="API_FOOTBALL_CACHE_MINUTES")
    api_football_close_window_minutes: int = Field(default=120, alias="API_FOOTBALL_CLOSE_WINDOW_MINUTES")
    gnews_enabled: bool = Field(default=False, alias="GNEWS_ENABLED")
    gnews_api_token: str | None = Field(default=None, alias="GNEWS_API_TOKEN")
    gnews_base_url: str = Field(default="https://gnews.io/api/v4", alias="GNEWS_BASE_URL")
    thesportsdb_enabled: bool = Field(default=False, alias="THESPORTSDB_ENABLED")
    thesportsdb_api_key: str | None = Field(default=None, alias="THESPORTSDB_API_KEY")
    thesportsdb_base_url: str = Field(default="https://www.thesportsdb.com/api/v1/json", alias="THESPORTSDB_BASE_URL")
    auto_olimp_scan_enabled: bool = Field(default=False, alias="AUTO_OLIMP_SCAN_ENABLED")
    auto_olimp_scan_interval_minutes: int = Field(default=30, alias="AUTO_OLIMP_SCAN_INTERVAL_MINUTES")
    auto_olimp_scan_match_limit: int = Field(default=12, alias="AUTO_OLIMP_SCAN_MATCH_LIMIT")
    auto_olimp_scan_send_empty: bool = Field(default=False, alias="AUTO_OLIMP_SCAN_SEND_EMPTY")

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @field_validator("database_url")
    @classmethod
    def normalize_database_url(cls, value: str) -> str:
        if value.startswith("postgres://"):
            return value.replace("postgres://", "postgresql+asyncpg://", 1)
        if value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+asyncpg://", 1)
        return value

    @field_validator("admin_user_id", mode="before")
    @classmethod
    def parse_optional_admin_user_id(cls, value: str | int | None) -> int | None:
        if value in (None, ""):
            return None
        return int(value)

    @field_validator("football_data_api_token", mode="before")
    @classmethod
    def parse_optional_football_data_token(cls, value: str | None) -> str | None:
        if value in (None, ""):
            return None
        return str(value).strip()

    @field_validator(
        "api_football_api_key",
        "gnews_api_token",
        "thesportsdb_api_key",
        mode="before",
    )
    @classmethod
    def parse_optional_api_token(cls, value: str | None) -> str | None:
        if value in (None, ""):
            return None
        return str(value).strip()

    @field_validator(
        "olimp_signal_priority_leagues_raw",
        "olimp_signal_league_allowlist_raw",
        "olimp_signal_league_blocklist_raw",
        mode="before",
    )
    @classmethod
    def normalize_csv_string(cls, value: str | list[str] | None) -> str:
        if value in (None, ""):
            return ""
        if isinstance(value, list):
            return ",".join(str(item).strip() for item in value if str(item).strip())
        return str(value).strip()

    @property
    def olimp_signal_priority_leagues(self) -> list[str]:
        return self._parse_csv_list(self.olimp_signal_priority_leagues_raw)

    @property
    def olimp_signal_league_allowlist(self) -> list[str]:
        return self._parse_csv_list(self.olimp_signal_league_allowlist_raw)

    @property
    def olimp_signal_league_blocklist(self) -> list[str]:
        return self._parse_csv_list(self.olimp_signal_league_blocklist_raw)

    @staticmethod
    def _parse_csv_list(value: str) -> list[str]:
        return [item.strip() for item in value.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
