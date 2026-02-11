from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, status

import services.db as db
from services import Services, get_services
from services.archive.thread_archive import archive_thread_events

router = APIRouter()


@router.post("/archive/{thread_ts}/")
def archive_thread_by_id(
    thread_ts: Annotated[
        str,
        Path(
            pattern=r"^p?\d+(?:\.\d+)?$",
            description=(
                "Slack thread timestamp (e.g. 1770792380.225759) or "
                "dotless permalink value (e.g. 1770792380225759 or p1770792380225759)."
            ),
        ),
    ],
    services: Annotated[Services, Depends(get_services)],
):
    kos_api_client = services.kos_api_client
    slack_engine = services.slack_db_engine

    with slack_engine.begin() as slack_conn:
        lookup_value = thread_ts[1:] if thread_ts.startswith("p") else thread_ts
        resolved_thread_ts = lookup_value
        if "." not in lookup_value:
            resolved_thread_ts = db.get_thread_ts_by_compact(slack_conn, lookup_value)
            if resolved_thread_ts is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={"message": "Thread not found"},
                )

        events = db.get_thread_events(slack_conn, resolved_thread_ts)
        if not events:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"message": "Thread not found"},
            )

        archive_path = archive_thread_events(
            thread_ts=resolved_thread_ts,
            slack_conn=slack_conn,
            kos_api_client=kos_api_client,
            events=events,
        )

    return {
        "thread_ts": resolved_thread_ts,
        "archive_path": str(archive_path),
        "event_count": len(events),
    }
