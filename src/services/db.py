import json
import logging

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from templates.sql import (
    CREATE_AUDIT_LOG_TABLE_SQL,
    CREATE_INTERVIEW_ANSWERS_SLACK_MODAL_TABLE_SQL,
    CREATE_SLACK_THREAD_EVENTS_TABLE_SQL,
    GET_APPLICANT_USER_ID_BY_THREAD_TS_SQL,
    GET_FORM_SUBMISSION_ID_BY_THREAD_TS_SQL,
    GET_MODAL_BLOCKS_PAYLOAD_SQL,
    GET_THREAD_EVENTS_SQL,
    GET_THREAD_TS_SQL,
    GET_THREAD_TS_BY_COMPACT_SQL,
    HAS_EMAIL_SENT_SQL,
    INSERT_AUDIT_LOG_SQL,
    INSERT_INTERVIEW_ANSWERS_SLACK_MODAL_SQL,
    INSERT_SLACK_EVENT_SQL,
)

logger = logging.getLogger(__name__)


def create_slack_db_engine(db_path: str) -> Engine:
    db_url = f"sqlite:///{db_path}"
    engine = create_engine(db_url, future=True)
    return engine


def create_slack_tables(conn_or_engine):
    if isinstance(conn_or_engine, Engine):
        with conn_or_engine.begin() as conn:
            _create_slack_tables(conn)
            _ensure_slack_thread_event_compact_ts(conn)
        return

    _create_slack_tables(conn_or_engine)
    _ensure_slack_thread_event_compact_ts(conn_or_engine)


def _create_slack_tables(conn) -> None:
    conn.execute(CREATE_SLACK_THREAD_EVENTS_TABLE_SQL)
    conn.execute(CREATE_INTERVIEW_ANSWERS_SLACK_MODAL_TABLE_SQL)
    conn.execute(CREATE_AUDIT_LOG_TABLE_SQL)


def _ensure_slack_thread_event_compact_ts(conn) -> None:
    columns = {
        row[1]
        for row in conn.execute(text("PRAGMA table_info(slack_thread_events)")).fetchall()
    }
    if "thread_ts_compact" not in columns:
        conn.execute(text("ALTER TABLE slack_thread_events ADD COLUMN thread_ts_compact TEXT"))

    conn.execute(
        text(
            """
            UPDATE slack_thread_events
            SET thread_ts_compact = REPLACE(thread_ts, '.', '')
            WHERE thread_ts IS NOT NULL
              AND (thread_ts_compact IS NULL OR thread_ts_compact = '')
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_slack_thread_events_thread_ts_compact
            ON slack_thread_events (thread_ts_compact)
            """
        )
    )


def get_thread_ts(conn, ts: str) -> str | None:
    result = conn.execute(GET_THREAD_TS_SQL, {"ts": ts}).fetchone()
    return result[0] if result else None


def get_thread_ts_by_compact(conn, thread_ts_compact: str) -> str | None:
    result = conn.execute(
        GET_THREAD_TS_BY_COMPACT_SQL,
        {"thread_ts_compact": thread_ts_compact},
    ).fetchone()
    return result[0] if result else None


def get_applicant_user_id_by_thread_ts(conn, thread_ts: str) -> str:
    result = conn.execute(
        GET_APPLICANT_USER_ID_BY_THREAD_TS_SQL,
        {"thread_ts": thread_ts},
    ).fetchone()
    return result[0] if result else None


def get_modal_blocks_payload_by_thread_ts(conn, thread_ts: str) -> dict:
    result = conn.execute(GET_MODAL_BLOCKS_PAYLOAD_SQL, {"thread_ts": thread_ts}).fetchone()
    return json.loads(result[0]) if result else None


def get_form_submission_id_by_thread_ts(conn, thread_ts: str) -> str | None:
    result = conn.execute(
        GET_FORM_SUBMISSION_ID_BY_THREAD_TS_SQL,
        {"thread_ts": thread_ts},
    ).fetchone()
    return result[0] if result else None


def insert_slack_event_row(conn, event_data: dict) -> None:
    conn.execute(INSERT_SLACK_EVENT_SQL, event_data)


def insert_interview_answers_slack_modal_row(
    conn,
    *,
    applicant_user_id: str,
    thread_ts: str,
    form_submission_id: str | None,
    slack_modal_blocks: str,
) -> None:
    conn.execute(
        INSERT_INTERVIEW_ANSWERS_SLACK_MODAL_SQL,
        {
            "applicant_user_id": applicant_user_id,
            "thread_ts": thread_ts,
            "form_submission_id": form_submission_id,
            "slack_modal_blocks": slack_modal_blocks,
        },
    )


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
        INSERT_AUDIT_LOG_SQL,
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
        GET_THREAD_EVENTS_SQL,
        {"thread_ts": thread_ts},
    ).fetchall()
    return [dict(row._mapping) for row in rows]


def has_email_sent(conn, thread_ts: str, email_type: str) -> bool:
    result = conn.execute(
        HAS_EMAIL_SENT_SQL,
        {"thread_ts": thread_ts, "email_type": f'%"email_type": "{email_type}"%'},
    ).fetchone()
    return result is not None
