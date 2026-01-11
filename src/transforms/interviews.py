from sqlalchemy import Engine

import config
from db import get_application_from_outbox, mark_outbox_failed, mark_outbox_success

import logging

import slack_web
logger = logging.getLogger(__name__)

def process_one(engine: Engine, outbox_id: int = None) -> bool:
    """
    Process a single outbox row.
    Returns True if work was done, False if queue is empty.
    """
    with engine.begin() as conn:
        row  = get_application_from_outbox(conn=conn, outbox_id=outbox_id)
        if row is None:
            logger.info("Nothing to process, returning.")
            return False

        try:
            logger.info("Processing submission %s", {row['form_submission_id']})
            slack_web.post_application(
                cfg=config.load_config(),
                application_data=row["data"],
            )
            
            mark_outbox_success(conn=conn, outbox_id=row["outbox_id"])

        except Exception as exc:
            logging.error("Failed to process outbox_id: %s", row["outbox_id"])
            mark_outbox_failed(conn=conn, outbox_id=outbox_id, exc=exc)
            raise

    return True