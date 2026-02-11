import asyncio
from dataclasses import dataclass

import pytest

import services.db as db
from core.config import Config
from slack.runtime import SlackRuntime


@dataclass
class FakeKosApiClient:
    user: dict

    def get_user(self, user_id: int):
        if self.user and int(self.user.get("id", -1)) == user_id:
            return self.user
        return None


@pytest.fixture()
def sample_user():
    return {"id": 999, "email": "test@example.com", "first_preferred": "Test"}


@pytest.fixture()
def kos_api_client(sample_user):
    return FakeKosApiClient(user=sample_user)


@pytest.fixture()
def slack_db_engine(tmp_path):
    db_path = tmp_path / "slack.db"
    engine = db.create_slack_db_engine(str(db_path))
    with engine.begin() as conn:
        db.create_slack_tables(conn)
    return engine


@pytest.fixture()
def cfg(tmp_path, slack_db_engine):
    return Config(
        kos_api_base_url="http://example.test",
        kos_api_token="token",
        kos_api_timeout_seconds=5,
        sqlite_db_path=str(tmp_path / "slack.db"),
        slack_bot_token="xoxb-test",
        slack_app_token="xapp-test",
        slack_channel_id="C123",
        authorized_usergroups=[],
        authorized_users=[],
        credentials_file=str(tmp_path / "credentials.json"),
        token_file=str(tmp_path / "token.json"),
        poll_interval_seconds=1,
        environment="test",
        debug=False,
        port=8080,
        api_token="test-api-token",
        project_root=str(tmp_path),
        archive_gdrive_url=None,
    )


@pytest.fixture()
def runtime(cfg, slack_db_engine, kos_api_client):
    runtime = SlackRuntime(
        slack_app=None,
        socket_handler=None,
        queue=asyncio.Queue(),
        slack_db_engine=slack_db_engine,
        kos_api_client=kos_api_client,
        config=cfg,
        mailer=object(),
    )
    return runtime
