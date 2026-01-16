import logging
import json
from fastapi import APIRouter, Request, Depends

import db
import slack_web
from services import Services, interviews

logger = logging.getLogger(__name__)


router = APIRouter()

def get_services(request: Request) -> Services:
    return request.app.state.services

@router.post("/process-form-outbox/{outbox_id}")
def process_outbox(outbox_id: int, request: Request, services: Services = Depends(get_services)):
    engine = services.kos_db_engine
    cfg = services.config
    slack_engine = services.slack_db_engine
    
    with engine.begin() as kos_conn, slack_engine.begin() as slack_conn:
        response = interviews.process_one(kos_conn=kos_conn, slack_conn=slack_conn, cfg=cfg, outbox_id=outbox_id)
    return {"ok": response.data["ok"], "channel": response.data.get("channel"), "ts": response.data.get("ts")}