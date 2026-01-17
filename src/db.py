import json
import logging

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

def create_slack_db_engine(db_path: str) -> Engine:
    db_url = f"sqlite:///{db_path}"
    engine = create_engine(db_url, future=True)
    return engine

# SQL for SQLite

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
    INSERT INTO slack_thread_events (thread_ts, user_id, user_name, event, message, parent_message, raw_response, timestamp, applicant_user_id)
    VALUES (:thread_ts, :user_id, :user_name, :event, :message, :parent_message, :raw_response, :timestamp, :applicant_user_id)
""")

INSERT_INTERVIEW_ANSWERS_SLACK_MODAL_SQL = text("""
    INSERT INTO interview_answers_slack_modal (applicant_user_id, thread_ts, slack_modal_blocks)
    VALUES (:applicant_user_id, :thread_ts, :slack_modal_blocks)
""")

def create_slack_tables(conn):
    conn.execute(CREATE_SLACK_THREAD_EVENTS_TABLE_SQL)
    conn.execute(CREATE_INTERVIEW_ANSWERS_SLACK_MODAL_TABLE_SQL)
    conn.execute(CREATE_AUDIT_LOG_TABLE_SQL)


def get_thread_ts(conn, ts: str) -> str:
    result = conn.execute(text("SELECT thread_ts FROM slack_thread_events WHERE timestamp = :ts LIMIT 1"), {"ts": ts}).fetchone()
    return result[0] if result else None


def get_applicant_user_id_by_thread_ts(conn, thread_ts: str) -> str:
    result = conn.execute(text("SELECT applicant_user_id FROM slack_thread_events WHERE thread_ts = :thread_ts AND event = 'post' LIMIT 1"), {"thread_ts": thread_ts}).fetchone()
    return result[0] if result else None


def get_modal_blocks_payload_by_thread_ts(conn, thread_ts: str) -> dict:
    result = conn.execute(text("SELECT slack_modal_blocks FROM interview_answers_slack_modal WHERE thread_ts = :thread_ts ORDER BY created_at DESC LIMIT 1"), {"thread_ts": thread_ts}).fetchone()
    return json.loads(result[0]) if result else None


def insert_audit_event(
    conn,
    *,
    action: str,
    actor_user_id: str | None,
    applicant_user_id: str | None,
    thread_ts: str | None,
    metadata: dict | None = None,
):
    conn.execute(
        text("""
            INSERT INTO audit_log (action, actor_user_id, applicant_user_id, thread_ts, metadata)
            VALUES (:action, :actor_user_id, :applicant_user_id, :thread_ts, :metadata)
        """),
        {
            "action": action,
            "actor_user_id": actor_user_id,
            "applicant_user_id": applicant_user_id,
            "thread_ts": thread_ts,
            "metadata": json.dumps(metadata or {}, ensure_ascii=True),
        },
    )


def get_thread_events(conn, thread_ts: str) -> list[dict]:
    rows = conn.execute(
        text("""
            SELECT thread_ts, user_id, user_name, event, message, parent_message,
                   raw_response, timestamp, applicant_user_id, created_at
            FROM slack_thread_events
            WHERE thread_ts = :thread_ts
            ORDER BY created_at ASC
        """),
        {"thread_ts": thread_ts},
    ).fetchall()
    return [dict(row._mapping) for row in rows]
