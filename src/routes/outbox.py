import logging
import json
from fastapi import APIRouter, Request, Depends

import db
import slack_web
from services import Services

logger = logging.getLogger(__name__)


router = APIRouter()

def get_services(request: Request) -> Services:
    return request.app.state.services

@router.post("/process-form-outbox/{outbox_id}")
def process_outbox(outbox_id: int, request: Request, services: Services = Depends(get_services)):
    engine = services.kos_db_engine
    cfg = services.config
    slack_engine = services.slack_db_engine
    
    with engine.begin() as conn:
        application = db.get_application_from_outbox(conn=conn, outbox_id=outbox_id)
        if not application:
            return {"No such outbox item"}
        try:
            logging.info("Processing submission %s", {application['form_submission_id']})
            response = slack_web.post_application(
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
                "applicant_user_id": application["user_id"],  # TODO: extract from application["data"] if available
            }
            db.insert_slack_event(slack_engine, event_data)
        except Exception as exc:
            logging.info("Failed to process outbox_id: %s", outbox_id)
            db.mark_outbox_failed(conn=conn, outbox_id=outbox_id, exc=exc)                
            return {f"Submission Failed {exc}"}

        db.mark_outbox_success(conn=conn, outbox_id=outbox_id)
        return {"Submission Successful"}