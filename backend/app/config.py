from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    openai_api_key: str | None = None
    alphavantage_api_key: str | None = None
    fmp_api_key: str | None = None
    database_url: str = "sqlite:///./data/tozsde_ai.db"
    refresh_cron_hour: int = 2
    refresh_cron_minute: int = 0
    timezone: str = "Europe/Budapest"
    sec_user_agent: str = "TozsdeAI/0.1 contact@example.com"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    def source_status(self) -> dict:
        return {
            "openai": {
                "configured": bool(self.openai_api_key),
                "role": "Magyar AI összefoglalók és filing/riport indoklások.",
                "fallback": "Szabályalapú magyar összefoglaló.",
            },
            "alphavantage": {
                "configured": bool(self.alphavantage_api_key),
                "role": "Napi árfolyam és volumen idősor.",
                "fallback": "Determinisztikus demo idősor, külön jelölve az adatminőségben.",
            },
            "fmp": {
                "configured": bool(self.fmp_api_key),
                "role": "Célár és elemzői konszenzus.",
                "fallback": "Semleges értékeltségi pontszám, missing_data jelzéssel.",
            },
            "sec": {
                "configured": True,
                "role": "SEC filingek és ticker-CIK feloldás.",
                "fallback": "Nem igényel API-kulcsot, csak user-agent beállítást.",
            },
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()
