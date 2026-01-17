import os
from pathlib import Path
from dataclasses import dataclass
from typing import Optional


def getenv(name: str, default: Optional[str] = None, *, required: bool = False) -> str:
    value = os.getenv(name, default)
    if required and value is None:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


@dataclass(frozen=True)
class Config:
    # kOS API
    kos_api_base_url: str
    kos_api_token: str
    kos_api_timeout_seconds: int

    #SQLite db
    sqlite_db_path: str

    # Slack
    slack_bot_token: str
    slack_app_token: str
    slack_channel_id: str

    authorized_usergroups: list

    # Email
    credentials_file: str
    token_file: str

    # Worker behavior
    poll_interval_seconds: int
    batch_size: int

    # Environment
    environment: str
    debug: bool
    
    port: int

    # Paths
    project_root: str


def load_config() -> Config:
    env = getenv("ENVIRONMENT", "development")
    project_root = Path(
        getenv("PROJECT_ROOT", str(Path(__file__).resolve().parent.parent))
    ).resolve()

    def resolve_path(value: str) -> str:
        path = Path(value)
        return str(path if path.is_absolute() else project_root / path)

    return Config(
        # Slack
        slack_bot_token=getenv("SLACK_BOT_TOKEN", required=True),
        slack_channel_id=getenv("SLACK_CHANNEL_ID", required=True),
        slack_app_token=getenv("SLACK_APP_TOKEN", required=True),

        #Default to BoD slack usergroup
        authorized_usergroups=getenv("AUTHORIZED_USERGROUPS", "SDFB4PKGE").split(" "), 

        poll_interval_seconds=int(getenv("POLL_INTERVAL_SECONDS", "30")),
        batch_size=int(getenv("BATCH_SIZE", "1")),
        
        # kOS API
        kos_api_base_url=getenv("KOS_API_BASE_URL", required=True),
        kos_api_token=getenv("KOS_API_TOKEN", required=True),
        kos_api_timeout_seconds=int(getenv("KOS_API_TIMEOUT_SECONDS", "10")),

        sqlite_db_path=resolve_path(getenv("SQLITE_DB_PATH", "slack_threads.db")),

        # Email
        credentials_file=resolve_path(getenv("CREDENTIALS_FILE", "credentials.json")),
        token_file=resolve_path(getenv("TOKEN_FILE", "token.json")),

        #API Service
        port=int(getenv("PORT", 8080)),

        # Meta
        environment=env,
        debug=getenv("DEBUG", "false").lower() == "true",

        # Paths
        project_root=str(project_root),
    )
