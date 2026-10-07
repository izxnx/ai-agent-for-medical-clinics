from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    app_env: str = "development"
    vapi_secret: str
    tg_bot_token: str = ""

    @field_validator("vapi_secret")
    @classmethod
    def validate_vapi_secret(cls, value, info):
        env = info.data.get("app_env", "development")
        if env.lower() != "test" and (not value.strip() or value.lower().startswith("change-me")):
            raise ValueError("VAPI_SECRET must be set to a non-placeholder secret")
        return value
    tg_admin_ids: str = ""  # "111,222" - особисті чати адмінів або id групи


settings = Settings()
