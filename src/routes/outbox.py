import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from jobs import interviews
from services import Services, get_services

logger = logging.getLogger(__name__)


router = APIRouter()


@router.post("/process-form-outbox/{outbox_id}")
def process_outbox(
    outbox_id: int,
    services: Annotated[Services, Depends(get_services)],
):
    kos_api_client = services.kos_api_client
    cfg = services.config
    slack_engine = services.slack_db_engine

    with slack_engine.begin() as slack_conn:
        try:
            response = interviews.process_one(
                kos_api_client=kos_api_client, slack_conn=slack_conn, cfg=cfg, outbox_id=outbox_id
            )
        except Exception as exc:
            logger.exception("Failed to process outbox item %s.", outbox_id)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={"message": "Failed to process outbox item"},
            ) from exc

    if hasattr(response, "data"):
        return {"ok": response.data.get("ok"), "channel": response.data.get("channel"), "ts": response.data.get("ts")}

    if response is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "Outbox item not found"},
        )
    return {"ok": False, "message": response}
