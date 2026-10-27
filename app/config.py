from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", validate_default=False)

    database_url: str = ""
    app_env: str = "development"
    # API key Retell з позначкою webhook: ним Retell підписує X-Retell-Signature,
    # і ним же бекенд читає дзвінок (recording_url) через Retell API.
    retell_api_key: str = ""
    tg_bot_token: str = ""
    tg_admin_ids: str = ""  # "111,222" - особисті чати адмінів або id групи
    forward_recordings_to_telegram: bool = False
    retell_recording_hosts: str = ""

    @field_validator("retell_api_key")
    @classmethod
    def validate_retell_api_key(cls, value, info):
        env = info.data.get("app_env", "development")
        normalized = value.strip()
        if env.lower() != "test" and (not normalized or normalized.lower().startswith("change-me")):
            raise ValueError("RETELL_API_KEY must be set")
        return normalized

    @field_validator("retell_recording_hosts")
    @classmethod
    def validate_recording_hosts(cls, value):
        hosts = []
        for item in value.split(","):
            host = item.strip().rstrip(".")
            if not host:
                continue
            if any(char in host for char in "/:@") or any(char.isspace() for char in host):
                raise ValueError("RETELL_RECORDING_HOSTS must contain hostnames only, separated by commas")
            try:
                hosts.append(host.encode("idna").decode("ascii").lower())
            except UnicodeError as exc:
                raise ValueError("RETELL_RECORDING_HOSTS contains an invalid hostname") from exc
        return ",".join(hosts)

    def validate_for_startup(self) -> None:
        if not self.database_url.strip():
            raise ValueError("DATABASE_URL must be set before startup")
        if self.app_env.lower() != "test" and (
            not self.retell_api_key.strip() or self.retell_api_key.lower().startswith("change-me")
        ):
            raise ValueError("RETELL_API_KEY must be set")
        if self.forward_recordings_to_telegram and not self.allowed_recording_hosts:
            raise ValueError(
                "RETELL_RECORDING_HOSTS must contain the recording hostname when recording forwarding is enabled"
            )

    @property
    def recording_forwarding_enabled(self) -> bool:
        return (
            self.forward_recordings_to_telegram
            and bool(self.retell_api_key.strip())
            and bool(self.allowed_recording_hosts)
        )

    @property
    def allowed_recording_hosts(self) -> set[str]:
        return {host for host in self.retell_recording_hosts.split(",") if host}


settings = Settings()
