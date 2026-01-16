from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
import config

import slack_web

import logging
import json
logger = logging.getLogger(__name__)

def create_kos_db_engine(config: config.Config) -> Engine:

    db_url = (
        f"mysql+pymysql://"
        f"{config.db_user}:{config.db_pass}"
        f"@{config.db_host}:{config.db_port}"
        f"/{config.db_name}"
    )

    engine = create_engine(
        db_url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        future=True,
    )

    return engine

def create_slack_db_engine() -> Engine:
    db_url = "sqlite:///slack_threads.db"
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


def get_thread_ts(conn, ts: str) -> str:
    result = conn.execute(text("SELECT thread_ts FROM slack_thread_events WHERE timestamp = :ts LIMIT 1"), {"ts": ts}).fetchone()
    return result[0] if result else None


def get_applicant_user_id_by_thread_ts(conn, thread_ts: str) -> str:
    result = conn.execute(text("SELECT applicant_user_id FROM slack_thread_events WHERE thread_ts = :thread_ts AND event = 'post' LIMIT 1"), {"thread_ts": thread_ts}).fetchone()
    return result[0] if result else None


def get_modal_blocks_payload_by_thread_ts(conn, thread_ts: str) -> dict:
    result = conn.execute(text("SELECT slack_modal_blocks FROM interview_answers_slack_modal WHERE thread_ts = :thread_ts ORDER BY created_at DESC LIMIT 1"), {"thread_ts": thread_ts}).fetchone()
    return json.loads(result[0]) if result else None


# SQL for KOS database
FETCH_USER_BY_ID_SQL = text("""
    SELECT 
        first_name,
        first_preferred,
        email
    FROM users
    WHERE id = :user_id
    """
)

FETCH_NEXT_OUTBOX_SQL = text("""
    SELECT
        o.id AS outbox_id,
        o.form_submission_id,
        s.form_name,
        s.data,
        s.created_at,
        s.user_id
    FROM form_submission_outbox o
    JOIN form_submissions s
        ON s.id = o.form_submission_id
    WHERE o.processed_at IS NULL
    ORDER BY o.created_at ASC
    LIMIT 1
    FOR UPDATE SKIP LOCKED;
""")

FETCH_OUTBOX_BY_ID_SQL = text("""
    SELECT
        o.id AS outbox_id,
        o.form_submission_id,
        s.form_name,
        s.data,
        s.created_at,
        s.user_id
    FROM form_submission_outbox o
    JOIN form_submissions s
        ON s.id = o.form_submission_id
    WHERE o.id = :outbox_id
    ORDER BY o.created_at ASC    
    FOR UPDATE SKIP LOCKED;
""")

MARK_PROCESSED_SQL = text("""
    UPDATE form_submission_outbox
    SET processed_at = NOW()
    WHERE id = :outbox_id
""")

MARK_FAILED_SQL = text("""
    UPDATE form_submission_outbox
    SET last_error = :error
    WHERE id = :outbox_id
""")

def get_user_by_id(conn, user_id: int) -> dict:
    """
    Get a single user given an id. Returns a dict representation of the row
    """
    if user_id is None:
        return None
    row = conn.execute(FETCH_USER_BY_ID_SQL, {"user_id": user_id}).mappings().first()
    return row
        

def mark_outbox_failed(conn, outbox_id: int, exc: Exception):
    conn.execute(
        MARK_FAILED_SQL,
        {
            "outbox_id": outbox_id,
            "error": str(exc)[:1000],
        },
    )
        
def mark_outbox_success(conn, outbox_id: int):
    conn.execute(
        MARK_PROCESSED_SQL,
        {"outbox_id": outbox_id},
    )
