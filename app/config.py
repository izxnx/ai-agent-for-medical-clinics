from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", validate_default=False)

    database_url: str = ""
    app_env: str = "development"
    vapi_secret: str = ""
    tg_bot_token: str = ""

    @field_validator("vapi_secret")
    @classmethod
    def validate_vapi_secret(cls, value, info):
        env = info.data.get("app_env", "development")
        normalized = value.strip()
        if env.lower() != "test" and (not normalized or normalized.lower().startswith("change-me")):
            raise ValueError("VAPI_SECRET must be set to a non-placeholder secret")
        return normalized

    def validate_for_startup(self) -> None:
        if not self.database_url.strip():
            raise ValueError("DATABASE_URL must be set before startup")
        if self.app_env.lower() != "test" and (not self.vapi_secret.strip() or self.vapi_secret.lower().startswith("change-me")):
            raise ValueError("VAPI_SECRET must be set to a non-placeholder secret")
    tg_admin_ids: str = ""  # "111,222" - особисті чати адмінів або id групи


settings = Settings()
