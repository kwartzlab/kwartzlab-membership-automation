import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import services.db as db


def _safe_filename(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", value.strip()) or "unknown"


def _get_preferred_name(user: Optional[dict]) -> tuple[str, str]:
    if not user:
        return "unknown", "unknown"
    first = (
        user.get("first_preferred")
        or user.get("preferred_first_name")
        or user.get("first_name")
        or user.get("first")
        or "unknown"
    )
    last = (
        user.get("last_preferred")
        or user.get("preferred_last_name")
        or user.get("last_name")
        or user.get("last")
        or "unknown"
    )
    return str(first), str(last)


def archive_thread_events(
    thread_ts: str,
    *,
    slack_conn,
    kos_api_client,
    output_dir: str | Path = "archives",
) -> Path:
    applicant_user_id = db.get_applicant_user_id_by_thread_ts(slack_conn, thread_ts) or "unknown"
    user = None
    if applicant_user_id != "unknown":
        user = kos_api_client.get_user(int(applicant_user_id))

    first_name, last_name = _get_preferred_name(user)
    date_str = datetime.now(timezone.utc).strftime("%Y%m%d")

    filename = (
        f"{_safe_filename(str(applicant_user_id))}_"
        f"{_safe_filename(first_name)}_{_safe_filename(last_name)}_{date_str}.jsonl"
    )
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    file_path = output_dir / filename

    events = db.get_thread_events(slack_conn, thread_ts)
    with file_path.open("w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event, ensure_ascii=True) + "\n")

    return file_path
