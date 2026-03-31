from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, status

import services.db as db
from services import Services, get_services
from services.archive.thread_archive import archive_thread_events

router = APIRouter()


@router.get("/archive/audit/")
def get_archive_audit(services: Annotated[Services, Depends(get_services)]):
    with services.slack_db_engine.connect() as conn:
        rows = db.get_unarchived_threads(conn)
    return {"unarchived_count": len(rows), "threads": rows}


@router.post("/archive/user/{kos_user_id}/")
def archive_thread_by_user(
    kos_user_id: Annotated[int, Path(description="kOS user ID")],
    services: Annotated[Services, Depends(get_services)],
):
    slack_engine = services.slack_db_engine

    with slack_engine.begin() as slack_conn:
        thread_ts = db.get_latest_thread_ts_by_applicant(slack_conn, str(kos_user_id))
        if thread_ts is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"message": f"No thread found for kOS user {kos_user_id}"},
            )

        events = db.get_thread_events(slack_conn, thread_ts)
        archive_path = archive_thread_events(
            thread_ts=thread_ts,
            slack_conn=slack_conn,
            kos_api_client=services.kos_api_client,
            events=events,
        )

    return {
        "kos_user_id": kos_user_id,
        "thread_ts": thread_ts,
        "archive_path": str(archive_path),
        "event_count": len(events),
    }


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
