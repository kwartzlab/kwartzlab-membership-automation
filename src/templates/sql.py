# SQL for SQLite

from sqlalchemy import text

CREATE_SLACK_THREAD_EVENTS_TABLE_SQL = text("""
    CREATE TABLE IF NOT EXISTS slack_thread_events (
        thread_ts TEXT,
        user_id TEXT,
        user_name TEXT,
        event TEXT,
        message TEXT,
        parent_message TEXT,
        raw_response TEXT,
        timestamp TEXT PRIMARY KEY,
        applicant_user_id TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
""")

CREATE_INTERVIEW_ANSWERS_SLACK_MODAL_TABLE_SQL = text("""
    CREATE TABLE IF NOT EXISTS interview_answers_slack_modal (
        id INTEGER PRIMARY KEY,
        applicant_user_id TEXT,
        thread_ts TEXT,
        slack_modal_blocks TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
""")

CREATE_AUDIT_LOG_TABLE_SQL = text("""
    CREATE TABLE IF NOT EXISTS audit_log (
        id INTEGER PRIMARY KEY,
        action TEXT,
        actor_user_id TEXT,
        applicant_user_id TEXT,
        thread_ts TEXT,
        metadata TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
""")

INSERT_SLACK_EVENT_SQL = text("""
    INSERT INTO slack_thread_events
        (thread_ts, user_id, user_name, event, message, parent_message, raw_response, timestamp, applicant_user_id)
    VALUES
        (:thread_ts, :user_id, :user_name, :event, :message,
        :parent_message, :raw_response, :timestamp, :applicant_user_id)
""")

INSERT_INTERVIEW_ANSWERS_SLACK_MODAL_SQL = text("""
    INSERT INTO interview_answers_slack_modal (applicant_user_id, thread_ts, slack_modal_blocks)
    VALUES (:applicant_user_id, :thread_ts, :slack_modal_blocks)
""")

GET_THREAD_TS_SQL = text("""
    SELECT thread_ts
    FROM slack_thread_events
    WHERE timestamp = :ts
    LIMIT 1
""")

GET_APPLICANT_USER_ID_BY_THREAD_TS_SQL = text("""
    SELECT applicant_user_id
    FROM slack_thread_events
    WHERE thread_ts = :thread_ts AND event = 'post'
    LIMIT 1
""")

GET_MODAL_BLOCKS_PAYLOAD_SQL = text("""
    SELECT slack_modal_blocks
    FROM interview_answers_slack_modal
    WHERE thread_ts = :thread_ts
    ORDER BY created_at DESC
    LIMIT 1
""")

INSERT_AUDIT_LOG_SQL = text("""
    INSERT INTO audit_log (action, actor_user_id, applicant_user_id, thread_ts, metadata)
    VALUES (:action, :actor_user_id, :applicant_user_id, :thread_ts, :metadata)
""")

GET_THREAD_EVENTS_SQL = text("""
    SELECT thread_ts, user_id, user_name, event, message, parent_message,
           raw_response, timestamp, applicant_user_id, created_at
    FROM slack_thread_events
    WHERE thread_ts = :thread_ts
    ORDER BY created_at ASC
""")

HAS_EMAIL_SENT_SQL = text("""
    SELECT 1
    FROM audit_log
    WHERE action = 'email_sent'
      AND thread_ts = :thread_ts
      AND metadata LIKE :email_type
    LIMIT 1
""")
