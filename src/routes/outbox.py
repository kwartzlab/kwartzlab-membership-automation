import logging
from fastapi import APIRouter, Request

import db
import slack

logger = logging.getLogger(__name__)


router = APIRouter()

@router.post("/process-form-outbox/{outbox_id}")
def process_outbox(outbox_id: int, request: Request):
    engine = request.app.state.engine
    cfg = request.app.state.cfg
    
    with engine.begin() as conn:
        engine = request.app.state.engine
        
        application = db.get_application_from_outbox(conn=conn, outbox_id=outbox_id)
        try:
            logging.info("Processing submission %s", {application['form_submission_id']})
            slack.post_application(
                    cfg=cfg,
                    application_data=application["data"],
                )
        except Exception as exc:
            logging.info("Failed to process outbox_id: %s", outbox_id)
            db.mark_outbox_failed(conn=conn, outbox_id=outbox_id, exc=exc)                
            return {f"Submission Failed {exc}"}

        db.mark_outbox_success(conn=conn, outbox_id=outbox_id)
        return {"Submission Successful"}