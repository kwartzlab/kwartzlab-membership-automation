import logging
from fastapi import APIRouter, Request, Depends

from services import Services, interviews

logger = logging.getLogger(__name__)


router = APIRouter()

def get_services(request: Request) -> Services:
    return request.app.state.services

@router.post("/process-form-outbox/{outbox_id}")
def process_outbox(outbox_id: int, request: Request, services: Services = Depends(get_services)):
    kos_api_client = services.kos_api_client
    cfg = services.config
    slack_engine = services.slack_db_engine
    
    with slack_engine.begin() as slack_conn:
        response = interviews.process_one(kos_api_client=kos_api_client, slack_conn=slack_conn, cfg=cfg, outbox_id=outbox_id)
    if hasattr(response, "data"):
        return {"ok": response.data.get("ok"), "channel": response.data.get("channel"), "ts": response.data.get("ts")}

    return {"ok": False, "message": response}
