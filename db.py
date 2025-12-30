# db.py
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
import config
import json

import slack

def create_db_engine(config: config.Config) -> Engine:

    # Compose MySQL URL from discrete config values
    db_url = (
        f"mysql+pymysql://"
        f"{config.db_user}:{config.db_pass}"
        f"@{config.db_host}:{config.db_port}"
        f"/{config.db_name}"
    )

    engine = create_engine(
        db_url,
        pool_pre_ping=True,   # avoid stale MySQL connections
        pool_size=5,
        max_overflow=5,
        future=True,
    )

    return engine


# Example repository-style helpers

FETCH_NEXT_SQL = text("""
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


def applicant_data_to_dict(data: str) -> dict:
    data_json = json.loads(data)
    return_dict = {}
    for uuid in data_json:
        return_dict[data_json[uuid]["label"]] = data_json[uuid]["value"]

    return return_dict


def process_one(engine: Engine) -> bool:
    """
    Process a single outbox row.
    Returns True if work was done, False if queue is empty.
    """
    with engine.begin() as conn:
        row = conn.execute(FETCH_NEXT_SQL).mappings().first()

        if row is None:
            return False

        try:
            # call postSlackMessage
            print(f"Processing submission {row['form_submission_id']}")
            
            slack.post_application(
                cfg=config.load_config(),
                applicant_data=applicant_data_to_dict(row["data"]),
            )
            
            conn.execute(
                MARK_PROCESSED_SQL,
                {"outbox_id": row["outbox_id"]},
            )

        except Exception as exc:
            conn.execute(
                MARK_FAILED_SQL,
                {
                    "outbox_id": row["outbox_id"],
                    "error": str(exc)[:1000],
                },
            )
            raise

    return True
