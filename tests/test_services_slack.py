import json

from sqlalchemy import text

from services.slack import slack as slack_service


def test_insert_slack_event_resolves_thread_and_applicant(slack_db_engine):
    with slack_db_engine.begin() as conn:
        post_event = {
            "thread_ts": "111.222",
            "user_id": "U1",
            "user_name": "User 1",
            "event": "post",
            "message": "hello",
            "parent_message": None,
            "raw_response": json.dumps({}),
            "timestamp": "111.222",
            "applicant_user_id": "999",
        }
        slack_service.insert_slack_event(conn, post_event)

        reaction_event = {
            "thread_ts": None,
            "user_id": "U2",
            "user_name": "User 2",
            "event": "react_add",
            "message": "white_check_mark",
            "parent_message": "111.222",
            "raw_response": json.dumps({}),
            "timestamp": "111.333",
            "applicant_user_id": None,
        }
        slack_service.insert_slack_event(conn, reaction_event)

        row = conn.execute(
            text("SELECT thread_ts, applicant_user_id FROM slack_thread_events WHERE event = 'react_add' LIMIT 1")
        ).fetchone()

        assert row[0] == "111.222"
        assert row[1] == "999"


def test_build_questions_modal_view_excludes_pii():
    application_data = {
        "1": {"label": "First Name", "value": "Test"},
        "2": {"label": "Last Name", "value": "User"},
        "3": {"label": "Email Address", "value": "test@example.com"},
        "4": {"label": "Phone Number", "value": "123-456"},
        "5": {"label": "What brings you here?", "value": "Making things"},
    }

    modal = slack_service.build_questions_modal_view(application_data)
    blocks_text = [block.get("text", {}).get("text", "") for block in modal["blocks"] if block.get("type") == "section"]

    combined = "\n".join(blocks_text)
    assert "Email:" in combined
    assert "Phone Number" not in combined
    assert "What brings you here?" in combined
