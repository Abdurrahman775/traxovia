from pydantic_settings import BaseSettings
from pydantic import ConfigDict, field_validator


class Settings(BaseSettings):
    model_config = ConfigDict(
        env_file=".env",
        extra="ignore",  # DB_HOST/PORT/NAME/USER/PASSWORD/SSLMODE read by sync_connection via os.getenv
    )

    database_url: str = ""
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"

    jwt_secret: str = ""

    @field_validator("jwt_secret")
    @classmethod
    def jwt_secret_must_be_set(cls, v: str) -> str:
        if not v or len(v) < 32:
            raise ValueError(
                "JWT_SECRET must be set and at least 32 characters long. "
                "Generate one with: python3 -c \"import secrets; print(secrets.token_hex(32))\""
            )
        return v
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60

    frontend_url: str = "http://localhost:3000"

    telegram_bot_token: str = ""
    telegram_community_channel_id: str = ""
    finnhub_api_key: str = ""

    app_env: str = "development"
    secret_key: str = ""
    cors_origins: str = "http://localhost:5173,http://localhost:3000"


settings = Settings()
