from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
import config

import slack as slack

import logging
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
        s.created_at
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
        s.created_at
    FROM form_submission_outbox o
    JOIN form_submissions s
        ON s.id = o.form_submission_id
    WHERE o.id = :outbox_id and o.processed_at IS NULL
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

def process_one(engine: Engine, outbox_id: int = None) -> bool:
    """
    Process a single outbox row.
    Returns True if work was done, False if queue is empty.
    """
    with engine.begin() as conn:
        row  = get_application_from_outbox(conn=conn, outbox_id=outbox_id)
        if row is None:
            logging.info("Nothing to process, returning.")
            return False

        try:
            logging.info("Processing submission %s", {row['form_submission_id']})
            slack.post_application(
                cfg=config.load_config(),
                applicantion_data=row["data"],
            )
            
            mark_outbox_success(conn=conn, outbox_id=row["outbox_id"])

        except Exception as exc:
            logging.error("Failed to process outbox_id: %s", row["outbox_id"])
            mark_outbox_failed(conn=conn, outbox_id=outbox_id, exc=exc)
            raise

    return True
