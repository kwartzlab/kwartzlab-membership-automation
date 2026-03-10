import logging

import pytest

import services.db as db
import services.mailer as mailer
from slack import slack_handlers
from slack.slack_handlers import reactions as reactions_module
from slack.slack_handlers import archive as archive_module


class FakeApp:
    def __init__(self):
        self.actions = {}
        self.shortcuts = {}
        self.events = {}
        self.views = {}

    def action(self, action_id):
        def decorator(fn):
            self.actions[action_id] = fn
            return fn

        return decorator

    def shortcut(self, name):
        def decorator(fn):
            self.shortcuts[name] = fn
            return fn

        return decorator

    def event(self, name):
        def decorator(fn):
            self.events[name] = fn
            return fn

        return decorator

    def view(self, callback_id):
        def decorator(fn):
            self.views[callback_id] = fn
            return fn

        return decorator


@pytest.mark.asyncio
async def test_reaction_email_sends_for_authorized_user(runtime, cfg, slack_db_engine, monkeypatch):
    sent = []
    ephemeral = []
    public = []

    def fake_send_message(service, user_id, message):
        sent.append((service, user_id, message))

    def fake_send_ephemeral_message(**kwargs):
        ephemeral.append(kwargs)

    def fake_post_message_reply(**kwargs):
        public.append(kwargs)

    monkeypatch.setattr(mailer, "send_message", fake_send_message)
    monkeypatch.setattr(reactions_module, "send_ephemeral_message", fake_send_ephemeral_message)
    monkeypatch.setattr(reactions_module, "post_message_reply", fake_post_message_reply)

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
                "form_submission_id": None,
            },
        )

    event = {
        "reaction": "white_check_mark",
        "user": "U1",
        "item": {"channel": cfg.slack_channel_id, "ts": "111.222"},
    }

    await reactions_module._handle_reaction_email(event, cfg, runtime)

    assert len(sent) == 0
    assert len(ephemeral) == 1
    assert ephemeral[0]["text"] == "Confirm sending email?"
    blocks = ephemeral[0].get("blocks", [])
    action_ids = {element.get("action_id") for block in blocks for element in block.get("elements", [])}
    assert "confirm_reaction_email" in action_ids
    assert "cancel_reaction_email" in action_ids
    assert len(public) == 0


@pytest.mark.asyncio
async def test_reaction_email_skips_unauthorized_user(runtime, cfg, slack_db_engine, monkeypatch):
    sent = []
    ephemeral = []
    public = []

    monkeypatch.setattr(mailer, "send_message", lambda *args, **kwargs: sent.append(1))
    monkeypatch.setattr(reactions_module, "send_ephemeral_message", lambda **kwargs: ephemeral.append(kwargs))
    monkeypatch.setattr(reactions_module, "post_message_reply", lambda **kwargs: public.append(kwargs))

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
                "form_submission_id": None,
            },
        )

    event = {
        "reaction": "white_check_mark",
        "user": "U2",
        "item": {"channel": cfg.slack_channel_id, "ts": "111.222"},
    }

    await reactions_module._handle_reaction_email(event, cfg, runtime)

    assert sent == []
    assert ephemeral == []
    assert public == []


@pytest.mark.asyncio
async def test_shortcut_includes_signature_inputs(runtime, cfg, monkeypatch):
    app = FakeApp()
    slack_handlers.register_email_shortcut_handler(app, cfg, runtime)

    opened_views = []

    class FakeClient:
        async def views_open(self, trigger_id, view):
            opened_views.append(view)

    runtime.cache_manager.authorized_users.add("U1")
    runtime.cache_manager.users_cache["U1"] = "Test User"

    async def ack():
        return None

    body = {
        "user": {"id": "U1"},
        "channel": {"id": cfg.slack_channel_id},
        "message": {"ts": "111.222", "thread_ts": "111.222"},
        "trigger_id": "TRIGGER",
    }

    await app.shortcuts["email_applicant"](ack, body, FakeClient(), logging.getLogger(__name__))

    assert opened_views
    block_ids = {block.get("block_id") for block in opened_views[0].get("blocks", [])}
    assert "signature_name_block" in block_ids
    assert "signature_role_block" in block_ids


@pytest.mark.asyncio
async def test_confirm_submit_sends_email(runtime, cfg, slack_db_engine, monkeypatch):
    app = FakeApp()
    slack_handlers.register_email_actions(app, cfg, runtime)

    sent = []
    ephemeral = []
    public = []
    responses = []
    archived = []

    monkeypatch.setattr(mailer, "send_message", lambda *args, **kwargs: sent.append(1))
    monkeypatch.setattr(reactions_module, "send_ephemeral_message", lambda **kwargs: ephemeral.append(kwargs))
    monkeypatch.setattr(reactions_module, "post_message_reply", lambda **kwargs: public.append(kwargs))
    monkeypatch.setattr(archive_module, "archive_thread_events", lambda **kwargs: archived.append(kwargs) or __import__("pathlib").Path("archive.csv"))

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
                "form_submission_id": None,
            },
        )

    async def ack():
        return None

    async def respond(**kwargs):
        responses.append(kwargs)

    body = {
        "user": {"id": "U1"},
        "actions": [{"action_id": "confirm_submit"}],
        "state": {
            "values": {
                "choice_block": {"choice_select": {"selected_option": {"value": "acceptance"}}},
                "bcc_block": {"bcc_self": {"selected_options": [{"value": "bcc_self"}]}},
            }
        },
        "container": {"thread_ts": "111.222"},
        "channel": {"id": cfg.slack_channel_id},
    }

    await app.actions["confirm_submit"](ack, body, logging.getLogger(__name__), respond)

    assert sent == [1]
    assert len(ephemeral) == 1
    assert len(public) == 1
    assert responses
    assert len(archived) == 1
    assert archived[0]["thread_ts"] == "111.222"
