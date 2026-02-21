import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


def getenv(name: str, default: Optional[str] = None, *, required: bool = False) -> str | None:
    value = os.getenv(name, default)
    if required and value is None:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


_PROJECT_ROOT_MARKERS = (".git", "pyproject.toml", "requirements.txt")


def _find_project_root(start: Path) -> Path:
    start = start.resolve()
    for parent in (start, *start.parents):
        if any((parent / marker).exists() for marker in _PROJECT_ROOT_MARKERS):
            return parent
    return start


@dataclass(frozen=True)
class Config:
    # kOS API
    kos_api_base_url: str
    kos_api_token: str
    kos_api_timeout_seconds: int

    # SQLite db
    sqlite_db_path: str

    # Slack
    slack_bot_token: str
    slack_app_token: str
    slack_channel_id: str

    authorized_usergroups: list[str]
    authorized_users: list[str]
    # Email
    credentials_file: str
    token_file: str
    google_admin_token_file: str
    google_workspace_domain: Optional[str]

    # Worker behavior
    poll_interval_seconds: int

    # Environment
    environment: str
    debug: bool

    port: int

    # API auth
    api_token: str

    # Paths
    project_root: str
    archive_gdrive_url: Optional[str]


def load_config() -> Config:
    env = getenv("ENVIRONMENT", "development")
    project_root_env = getenv("PROJECT_ROOT")
    if project_root_env:
        project_root = Path(project_root_env).expanduser().resolve()
    else:
        project_root = _find_project_root(Path(__file__).resolve().parent)
        if project_root == Path(__file__).resolve().parent:
            project_root = _find_project_root(Path.cwd())

    def resolve_path(value: str) -> str:
        path = Path(value)
        return str(path if path.is_absolute() else project_root / path)

    return Config(
        # Slack
        slack_bot_token=getenv("SLACK_BOT_TOKEN", required=True),
        slack_channel_id=getenv("SLACK_CHANNEL_ID", required=True),
        slack_app_token=getenv("SLACK_APP_TOKEN", required=True),
        # Default to BoD slack usergroup
        authorized_usergroups=getenv("AUTHORIZED_USERGROUPS", "SDFB4PKGE").split(" "),
        authorized_users=getenv("AUTHORIZED_USERS", "").split(" "),
        # kOS API
        kos_api_base_url=getenv("KOS_API_BASE_URL", required=True),
        kos_api_token=getenv("KOS_API_TOKEN", required=True),
        kos_api_timeout_seconds=int(getenv("KOS_API_TIMEOUT_SECONDS", "10")),
        poll_interval_seconds=int(getenv("POLL_INTERVAL_SECONDS", "30")),
        # SQLite db
        sqlite_db_path=resolve_path(getenv("SQLITE_DB_PATH", "./database/slack_threads.db")),
        # Google API
        credentials_file=resolve_path(getenv("CREDENTIALS_FILE", "credentials.json")),
        token_file=resolve_path(getenv("TOKEN_FILE", "token.json")),
        google_admin_token_file=resolve_path(getenv("GOOGLE_ADMIN_TOKEN_FILE", "token_admin.json")),
        google_workspace_domain=getenv("GOOGLE_WORKSPACE_DOMAIN"),
        archive_gdrive_url=getenv("ARCHIVE_GDRIVE_URL"),
        # API Service
        port=int(getenv("PORT", 8080)),
        # Meta
        environment=env,
        debug=getenv("DEBUG", "false").lower() == "true",
        # API auth
        api_token=getenv("API_TOKEN", required=True),
        # Paths
        project_root=str(project_root),
    )
