from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # --- Инфраструктура ---
    DATABASE_URL: str = "postgresql+asyncpg://app:app@postgres:5432/app"
    REDIS_URL: str = "redis://redis:6379/0"
    CORS_ORIGINS: str = "http://localhost"
    DEBUG: bool = False

    # --- LLM (RouterAI / любой OpenAI-совместимый; mock работает без сети) ---
    LLM_PROVIDER: str = "mock"          # mock | openai_compat
    LLM_BASE_URL: str = ""
    LLM_API_KEY: str = ""
    LLM_MODEL: str = ""

    # --- Параметры обработки ---
    TG_FETCH_LIMIT: int = 100           # максимум постов на канал за прогон
    TG_FETCH_DAYS: int = 7              # глубина чтения канала
    FILTER_BATCH: int = 30              # размер батча message-filter
    NEWSMAKER_CAP: int = 100            # максимум relevant-сообщений в news-maker

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
