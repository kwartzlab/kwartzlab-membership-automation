import os
from dataclasses import dataclass
from typing import Optional


def getenv(name: str, default: Optional[str] = None, *, required: bool = False) -> str:
    value = os.getenv(name, default)
    if required and value is None:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


@dataclass(frozen=True)
class Config:
    # Database
    db_user: str
    db_pass: str
    db_host: str
    db_port: int
    db_name: str

    # Slack
    slack_bot_token: str
    slack_channel_id: str

    # Worker behavior
    poll_interval_seconds: int
    batch_size: int

    # Environment
    environment: str
    debug: bool


def load_config() -> Config:
    env = getenv("ENVIRONMENT", "development")

    return Config(
        # Slack
        slack_bot_token=getenv("SLACK_BOT_TOKEN", required=True),
        slack_channel_id=getenv("SLACK_CHANNEL_ID", required=True),

        poll_interval_seconds=int(getenv("POLL_INTERVAL_SECONDS", "30")),
        batch_size=int(getenv("BATCH_SIZE", "1")),
        
        # db
        db_user=getenv("DB_USERNAME", required=True),
        db_pass=getenv("DB_PASSWORD", required=True),
        db_host=getenv("DB_HOST", required=True),
        db_port=getenv("DB_PORT", required=True),
        db_name=getenv("DB_DATABASE", required=True),

        # Meta
        environment=env,
        debug=getenv("DEBUG", "false").lower() == "true"
    )