from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_FILE = Path(".env")
"""Read beside the working directory, which is why the service sets one."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore")

    infomentor_username: str
    infomentor_password: str

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    smtp_host: str = ""
    smtp_port: int = 25
    mail_from: str = ""
    mail_to: str = ""

    headed: bool = False
    data_dir: Path = Path("data")
    days_ahead: int = 21
    run_at: str = "18:30"

    @property
    def state_file(self) -> Path:
        return self.data_dir / "reported.json"

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id)

    @property
    def mail_enabled(self) -> bool:
        return bool(self.smtp_host and self.mail_to)
