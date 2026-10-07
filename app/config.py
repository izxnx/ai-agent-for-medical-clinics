from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    vapi_secret: str
    tg_bot_token: str = ""
    tg_admin_ids: str = ""  # "111,222" - особисті чати адмінів або id групи


settings = Settings()
