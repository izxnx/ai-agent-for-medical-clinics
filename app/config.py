from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", validate_default=False)

    database_url: str = ""
    app_env: str = "development"
    vapi_secret: str = ""
    tg_bot_token: str = ""
    tg_admin_ids: str = ""  # "111,222" - особисті чати адмінів або id групи
    vapi_recording_hosts: str = ""

    @field_validator("vapi_secret")
    @classmethod
    def validate_vapi_secret(cls, value, info):
        env = info.data.get("app_env", "development")
        normalized = value.strip()
        if env.lower() != "test" and (not normalized or normalized.lower().startswith("change-me")):
            raise ValueError("VAPI_SECRET must be set to a non-placeholder secret")
        return normalized

    @field_validator("vapi_recording_hosts")
    @classmethod
    def validate_recording_hosts(cls, value):
        hosts = []
        for item in value.split(","):
            host = item.strip().rstrip(".")
            if not host:
                continue
            if any(char in host for char in "/:@") or any(char.isspace() for char in host):
                raise ValueError("VAPI_RECORDING_HOSTS must contain hostnames only, separated by commas")
            try:
                hosts.append(host.encode("idna").decode("ascii").lower())
            except UnicodeError as exc:
                raise ValueError("VAPI_RECORDING_HOSTS contains an invalid hostname") from exc
        return ",".join(hosts)

    def validate_for_startup(self) -> None:
        if not self.database_url.strip():
            raise ValueError("DATABASE_URL must be set before startup")
        if self.app_env.lower() != "test" and (not self.vapi_secret.strip() or self.vapi_secret.lower().startswith("change-me")):
            raise ValueError("VAPI_SECRET must be set to a non-placeholder secret")

    @property
    def allowed_recording_hosts(self) -> set[str]:
        return {host for host in self.vapi_recording_hosts.split(",") if host}


settings = Settings()
