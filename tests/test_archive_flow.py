from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy import text

import services.db as db
from slack import slack_handlers
from slack.slack_handlers import archive as archive_module


class FakeApp:
    def __init__(self):
        self.shortcuts = {}

    def shortcut(self, name):
        def decorator(fn):
            self.shortcuts[name] = fn
            return fn

        return decorator


@pytest.mark.asyncio
async def test_archive_shortcut_writes_audit_and_ephemeral(runtime, cfg, slack_db_engine, monkeypatch):
    archive_cfg = replace(cfg, archive_gdrive_url="https://drive.example")
    runtime.config = archive_cfg

    app = FakeApp()
    slack_handlers.register_archive_shortcut_handler(app, archive_cfg, runtime)

    runtime.cache_manager.authorized_users.add("U1")
    with slack_db_engine.begin() as conn:
        conn.execute(
            db.INSERT_SLACK_EVENT_SQL,
            {
                "thread_ts": "111.222",
                "user_id": "U1",
                "user_name": "User 1",
                "event": "post",
                "message": "hello",
                "parent_message": None,
                "raw_response": "{}",
                "timestamp": "111.222",
                "applicant_user_id": "999",
            },
        )

    monkeypatch.setattr(archive_module, "archive_thread_events", lambda **kwargs: Path("archive.zip"))
    monkeypatch.setattr(
        archive_module.drive_archive, "upload_file_to_drive", lambda *args, **kwargs: "https://drive.example/file"
    )

    ephemeral = []
    monkeypatch.setattr(archive_module, "send_ephemeral_message", lambda **kwargs: ephemeral.append(kwargs))

    async def ack():
        return None

    body = {
        "user": {"id": "U1"},
        "channel": {"id": archive_cfg.slack_channel_id},
        "message": {"thread_ts": "111.222", "ts": "111.222"},
    }

    await app.shortcuts["archive_thread"](ack, body, None)

    assert len(ephemeral) == 1
    assert "Thread archived to" in ephemeral[0]["text"]
    assert "Uploaded to Drive" in ephemeral[0]["text"]

    with slack_db_engine.connect() as conn:
        row = conn.execute(
            text("SELECT action, metadata FROM audit_log WHERE action = 'thread_archived' LIMIT 1")
        ).fetchone()

    assert row is not None
    assert row[0] == "thread_archived"
