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


@lru_cache
def get_settings() -> Settings:
    return Settings()
