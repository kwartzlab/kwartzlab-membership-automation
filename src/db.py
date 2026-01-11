from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
import config

import slack_web

import logging
import json
logger = logging.getLogger(__name__)

def create_db_engine(config: config.Config) -> Engine:

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

CREATE_SLACK_THREAD_EVENTS_TABLE_SQL = text("""
    CREATE TABLE IF NOT EXISTS slack_thread_events (
        thread_ts TEXT,
        user_id TEXT,
        user_name TEXT,
        event TEXT,
        message TEXT,
        parent_message TEXT,
        raw_response TEXT,
        timestamp TEXT,
        applicant_user_id TEXT
    )
""")

INSERT_SLACK_EVENT_SQL = text("""
    INSERT INTO slack_thread_events (thread_ts, user_id, user_name, event, message, parent_message, raw_response, timestamp, applicant_user_id)
    VALUES (:thread_ts, :user_id, :user_name, :event, :message, :parent_message, :raw_response, :timestamp, :applicant_user_id)
""")

def create_slack_tables(engine: Engine):
    with engine.begin() as conn:
        conn.execute(CREATE_SLACK_THREAD_EVENTS_TABLE_SQL)

def get_thread_ts(engine: Engine, ts: str) -> str:
    with engine.begin() as conn:
        result = conn.execute(text("SELECT thread_ts FROM slack_thread_events WHERE timestamp = :ts LIMIT 1"), {"ts": ts}).fetchone()
        return result[0] if result else None

def get_applicant_user_id_by_thread_ts(engine: Engine, thread_ts: str) -> str:
    with engine.begin() as conn:
        result = conn.execute(text("SELECT applicant_user_id FROM slack_thread_events WHERE thread_ts = :thread_ts AND event = 'post' LIMIT 1"), {"thread_ts": thread_ts}).fetchone()
        return result[0] if result else None

def insert_slack_event(engine: Engine, event_data: dict):
    # Resolve thread_ts for reactions if needed
    if event_data.get('thread_ts') is None and event_data.get('parent_message'):
        event_data['thread_ts'] = get_thread_ts(engine, event_data['parent_message'])
    
    # Set applicant_user_id if not set and thread_ts exists
    if event_data.get('applicant_user_id') is None and event_data.get('thread_ts'):
        event_data['applicant_user_id'] = get_applicant_user_id_by_thread_ts(engine, event_data['thread_ts'])
    
    with engine.begin() as conn:
        conn.execute(INSERT_SLACK_EVENT_SQL, event_data)

def update_slack_user_names(engine: Engine):
    with engine.begin() as conn:
        result = conn.execute(text("SELECT DISTINCT user_id FROM slack_thread_events WHERE user_name IS NULL OR user_name = ''"))
        user_ids = [row[0] for row in result.fetchall()]

        from slack_sdk import WebClient
        from slack_sdk.errors import SlackApiError

        client = WebClient(token=config.load_config().slack_bot_token)

        for user_id in user_ids:
            try:
                response = client.users_info(user=user_id)
                user_name = response['user']['real_name']
                conn.execute(
                    text("UPDATE slack_thread_events SET user_name = :user_name WHERE user_id = :user_id"),
                    {"user_name": user_name, "user_id": user_id}
                )
            except SlackApiError as e:
                logger.error(f"Failed to fetch user info for {user_id}: {e.response['error']}")


def get_slack_event_by_message_ts(engine: Engine, message_ts: str) -> dict:
    with engine.begin() as conn:
        result = conn.execute(
            text("SELECT * FROM slack_thread_events WHERE timestamp = :message_ts LIMIT 1"),
            {"message_ts": message_ts}
        ).mappings().first()
        return result


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


def get_application_from_outbox(conn, outbox_id: int = None):
    if outbox_id is None:
        logger.info("Fetching next outbox item")
        row = conn.execute(FETCH_NEXT_OUTBOX_SQL).mappings().first()
    else: 
        logger.info("Fetching outbox by id %s", outbox_id)
        row = conn.execute(FETCH_OUTBOX_BY_ID_SQL, {"outbox_id": outbox_id}).mappings().first()

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

def archive_slack_message(item: dict):
    """
    Archive a slack message to the database.
    item contains: engine, channel, user, text, ts, thread_ts
    """
    engine = item["engine"]
    # with engine.begin() as conn:
    #     conn.execute(
    #         text("""
    #             INSERT INTO slack_messages (channel, user, text, ts, thread_ts)
    #             VALUES (:channel, :user, :text, :ts, :thread_ts)
    #         """),
    #         {
    #             "channel": item["channel"],
    #             "user": item["user"],
    #             "text": item["text"],
    #             "ts": item["ts"],
    #             "thread_ts": item["thread_ts"],
    #         },
    #     )


def process_one(engine: Engine, slack_engine: Engine, cfg):
    with engine.begin() as conn:
        row = get_application_from_outbox(conn)
        if not row:
            return
        response = slack_web.post_application(cfg, row['data'])
        ts = response['ts']
        data_dict = slack_web.applicant_data_to_dict(row['data'])
        applicant_user_id = data_dict.get("User ID")  # assume the label is "User ID"
        event_data = {
            "thread_ts": ts,
            "user_id": "bot",
            "user_name": "bot",
            "event": "post",
            "message": "",  # TODO: extract text from blocks if needed
            "parent_message": None,
            "raw_response": json.dumps(response.data),
            "timestamp": ts,
            "applicant_user_id": applicant_user_id,
            }
        insert_slack_event(slack_engine, event_data)
        mark_outbox_success(conn, row['outbox_id'])