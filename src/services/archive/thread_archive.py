import csv
import re
from pathlib import Path
from typing import Optional

import services.db as db
import services.kos_api as kos_api


def _safe_filename(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", value.strip()) or "unknown"


def _get_preferred_name(user: Optional[dict]) -> tuple[str, str]:
    if not user:
        return "unknown", "unknown"
    first = kos_api.get_user_first_name(user, default="unknown")
    last = kos_api.get_user_last_name(user, default="unknown")
    return first, last


def archive_thread_events(
    thread_ts: str,
    slack_conn,
    kos_api_client,
    output_dir: str | Path = "archives",
    events: Optional[list[dict]] = None,
) -> Path:
    applicant_user_id = db.get_applicant_user_id_by_thread_ts(slack_conn, thread_ts) or "unknown"
    user = None
    if applicant_user_id != "unknown":
        user = kos_api_client.get_user(int(applicant_user_id))

    first_name, last_name = _get_preferred_name(user)

    filename = f"{_safe_filename(str(applicant_user_id))}_{_safe_filename(first_name)}_{_safe_filename(last_name)}.csv"
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    file_path = output_dir / filename

    if events is None:
        events = db.get_thread_events(slack_conn, thread_ts)
    fieldnames = [
        "thread_ts",
        "form_submission_id",
        "user_id",
        "user_name",
        "event",
        "message",
        "parent_message",
        "raw_response",
        "timestamp",
        "applicant_user_id",
        "created_at",
    ]
    with file_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        for event in events:
            writer.writerow({name: event.get(name) or "" for name in fieldnames})

    return file_path
