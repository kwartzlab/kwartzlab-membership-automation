import asyncio
import logging

import services.db as db
from services.archive import drive_archive
from services.archive.thread_archive import archive_thread_events

logger = logging.getLogger(__name__)

MAX_UNARCHIVED_DISPLAY = 20


def archive_dm_help_text() -> str:
    return (
        "Archive DM commands:\n"
        "- `audit archives`: list threads not yet archived\n"
        "- `archive user <kos_user_id>`: archive the most recent thread for a kOS user\n"
        "- `archive <thread_ts>`: archive a specific thread by timestamp"
    )


async def handle_archive_dm_command(text: str, *, user_id: str, say, cfg, runtime) -> bool:
    lowered = text.lower().strip()

    if lowered == "audit archives":
        await _handle_audit_archives(say=say, runtime=runtime)
        return True

    if lowered.startswith("archive user "):
        raw = text.strip().split(None, 2)
        if len(raw) < 3 or not raw[2].strip().isdigit():
            await say("Usage: `archive user <kos_user_id>`")
            return True
        kos_user_id = raw[2].strip()
        await _handle_archive_by_user(kos_user_id=kos_user_id, actor_user_id=user_id, say=say, cfg=cfg, runtime=runtime)
        return True

    if lowered.startswith("archive "):
        raw = text.strip().split(None, 1)
        thread_ts = raw[1].strip() if len(raw) > 1 else ""
        if not thread_ts:
            await say("Usage: `archive <thread_ts>`")
            return True
        await _handle_archive_by_thread(thread_ts=thread_ts, actor_user_id=user_id, say=say, cfg=cfg, runtime=runtime)
        return True

    return False


async def _handle_audit_archives(*, say, runtime) -> None:
    def _query(conn):
        return db.get_unarchived_threads(conn)

    with runtime.slack_db_engine.connect() as conn:
        rows = await asyncio.to_thread(_query, conn)

    if not rows:
        await say("All threads have been archived.")
        return

    lines = []
    for row in rows[:MAX_UNARCHIVED_DISPLAY]:
        thread_ts = row.get("thread_ts", "")
        applicant_id = row.get("applicant_user_id") or "unknown"
        email_type = row.get("last_email_type")
        status_label = f"last email: {email_type}" if email_type else "no email sent"
        lines.append(f"• `{thread_ts}` — kOS user {applicant_id} ({status_label})")

    remaining = len(rows) - MAX_UNARCHIVED_DISPLAY
    summary = f"*Unarchived threads* ({len(rows)})\n" + "\n".join(lines)
    if remaining > 0:
        summary += f"\n_...and {remaining} more_"

    await say(blocks=[{"type": "section", "text": {"type": "mrkdwn", "text": summary}}], text=summary)


async def _do_archive(*, thread_ts: str, actor_user_id: str, say, cfg, runtime) -> None:
    def _run(conn):
        applicant_user_id = db.get_applicant_user_id_by_thread_ts(conn, thread_ts)
        archive_path = archive_thread_events(
            thread_ts=thread_ts,
            slack_conn=conn,
            kos_api_client=runtime.kos_api_client,
        )
        db.insert_audit_event(
            conn,
            action="thread_archived",
            actor_user_id=actor_user_id,
            applicant_user_id=applicant_user_id,
            thread_ts=thread_ts,
            metadata={"archive_path": str(archive_path), "archive_gdrive_url": None},
        )
        return archive_path

    with runtime.slack_db_engine.begin() as conn:
        archive_path = await asyncio.to_thread(_run, conn)

    drive_link = None
    if cfg.archive_gdrive_url:
        try:
            drive_link = await asyncio.to_thread(
                drive_archive.upload_file_to_drive,
                archive_path,
                cfg.archive_gdrive_url,
                credentials_file=cfg.credentials_file,
                token_file=cfg.token_file,
            )
        except Exception:
            logger.exception("Failed to upload archive to Google Drive for thread %s.", thread_ts)

    msg = f"Archived `{thread_ts}` to `{archive_path}`."
    if drive_link:
        msg += f" Uploaded to Drive: {drive_link}"
    await say(msg)


async def _handle_archive_by_user(*, kos_user_id: str, actor_user_id: str, say, cfg, runtime) -> None:
    with runtime.slack_db_engine.connect() as conn:
        thread_ts = db.get_latest_thread_ts_by_applicant(conn, kos_user_id)

    if not thread_ts:
        await say(f"No thread found for kOS user {kos_user_id}.")
        return

    await _do_archive(thread_ts=thread_ts, actor_user_id=actor_user_id, say=say, cfg=cfg, runtime=runtime)


async def _handle_archive_by_thread(*, thread_ts: str, actor_user_id: str, say, cfg, runtime) -> None:
    with runtime.slack_db_engine.connect() as conn:
        if "." not in thread_ts:
            thread_ts = db.get_thread_ts_by_compact(conn, thread_ts.lstrip("p")) or thread_ts
        events = db.get_thread_events(conn, thread_ts)

    if not events:
        await say(f"No thread found for `{thread_ts}`.")
        return

    await _do_archive(thread_ts=thread_ts, actor_user_id=actor_user_id, say=say, cfg=cfg, runtime=runtime)
