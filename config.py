from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    database_url: str = ""
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"

    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_role_key: str = ""
    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60

    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_price_starter: str = ""
    stripe_price_trader: str = ""
    stripe_price_pro: str = ""
    stripe_price_elite: str = ""
    frontend_url: str = "http://localhost:3000"

    mt5_bridge_primary_url: str = ""
    mt5_bridge_standby_url: str = ""
    mt5_bridge_api_key: str = ""
    mt5_bridge_heartbeat_interval: int = 60
    mt5_bridge_failover_timeout: int = 120

    telegram_bot_token: str = ""
    telegram_community_channel_id: str = ""

    app_env: str = "development"
    secret_key: str = ""

    class Config:
        env_file = ".env"
        extra = "ignore"  # DB_HOST/PORT/NAME/USER/PASSWORD/SSLMODE read by sync_connection via os.getenv


settings = Settings()
