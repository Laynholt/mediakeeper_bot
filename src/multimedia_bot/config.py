from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    bot_token: str = Field(alias="BOT_TOKEN")
    telegram_storage_chat_id: int = Field(alias="TELEGRAM_STORAGE_CHAT_ID")
    admin_user_id: int | None = Field(default=None, alias="ADMIN_USER_ID")
    database_url: str = Field(
        default="sqlite+aiosqlite:///./data/multimedia_bot.db",
        alias="DATABASE_URL",
    )
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    inline_cache_time: int = Field(default=30, alias="INLINE_CACHE_TIME")
    search_limit: int = Field(default=20, alias="SEARCH_LIMIT")
    export_part_size_mb: int = Field(default=1900, alias="EXPORT_PART_SIZE_MB")
    media_root: Path = Field(default=Path("stuff/media"), alias="MEDIA_ROOT")
    admin_user_ids_raw: str = Field(default="", alias="ADMIN_USER_IDS")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def resolve_admin_user_id(explicit_value: int | None, legacy_value: str) -> int | None:
    if explicit_value is not None:
        return explicit_value
    if not legacy_value.strip():
        return None
    first_value = legacy_value.split(",", 1)[0].strip()
    return int(first_value) if first_value else None
