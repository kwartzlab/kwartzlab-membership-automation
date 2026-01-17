import db


def test_get_thread_ts_and_applicant(slack_db_engine):
    with slack_db_engine.begin() as conn:
        event_data = {
            "thread_ts": "111.222",
            "user_id": "U1",
            "user_name": "User 1",
            "event": "post",
            "message": "hello",
            "parent_message": None,
            "raw_response": "{}",
            "timestamp": "111.222",
            "applicant_user_id": "999",
        }
        conn.execute(db.INSERT_SLACK_EVENT_SQL, event_data)

        assert db.get_thread_ts(conn, "111.222") == "111.222"
        assert db.get_applicant_user_id_by_thread_ts(conn, "111.222") == "999"
