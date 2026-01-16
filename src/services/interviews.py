import json
from sqlalchemy import Connection

import config
from db import FETCH_OUTBOX_BY_ID_SQL, FETCH_NEXT_OUTBOX_SQL, mark_outbox_failed, mark_outbox_success
from services.slack import add_default_message, add_default_reacts, insert_slack_event, post_application, build_questions_modal_view, save_slack_modal_response

import logging

logger = logging.getLogger(__name__)

def process_one(kos_conn: Connection, slack_conn: Connection, cfg: config.Config, outbox_id: int = None):

    application = get_application_from_outbox(conn=kos_conn, outbox_id=outbox_id)
    if not application:
        return {"No such outbox item"}
    try:
        logging.info("Processing submission %s", {application['form_submission_id']})
        response = post_application(
                cfg=cfg,
                application_data=application["data"],
            )
        ts = response['ts']
        event_data = {
            "thread_ts": ts,
            "user_id": "bot",
            "user_name": "bot",
            "event": "post",
            "message": "",
            "parent_message": None,
            "raw_response": json.dumps(response.data),
            "timestamp": ts,
            "applicant_user_id": application["user_id"],
        }
        insert_slack_event(slack_conn, event_data)
        
        add_default_reacts(cfg, channel=response['channel'], timestamp=ts)
        add_default_message(cfg, channel=response['channel'], timestamp=ts)
        
        modal = build_questions_modal_view(application_data=application["data"])
        logger.info("Saving slack modal response for user %s", application["user_id"])
        
        save_slack_modal_response(
            conn=slack_conn,
            applicant_user_id=application["user_id"],
            thread_ts=ts,
            slack_modal_blocks=json.dumps(modal),
        )
        return response
        
    except Exception as exc:
        logging.info("Failed to process outbox_id: %s", outbox_id)
        mark_outbox_failed(conn=kos_conn, outbox_id=outbox_id, exc=exc)                
        return {f"Submission Failed {exc}"}

    mark_outbox_success(conn=kos_conn, outbox_id=outbox_id)
    return {"Submission Successful"}

    
def get_application_from_outbox(conn, outbox_id: int = None):
    if outbox_id is None:
        logger.info("Fetching next outbox item")
        row = conn.execute(FETCH_NEXT_OUTBOX_SQL).mappings().first()
    else: 
        logger.info("Fetching outbox by id %s", outbox_id)
        row = conn.execute(FETCH_OUTBOX_BY_ID_SQL, {"outbox_id": outbox_id}).mappings().first()

    return row