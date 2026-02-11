import asyncio
import logging

import services.db as db
from services.archive import drive_archive
from services.archive.thread_archive import archive_thread_events
from services.slack.slack_web import send_ephemeral_message

logger = logging.getLogger(__name__)


def register_archive_shortcut_handler(app, cfg, runtime):
    @app.shortcut("archive_thread")
    async def handle_archive_shortcut(ack, body, logger):
        await ack()

        user_id = body.get("user", {}).get("id")
        channel_id = body.get("channel", {}).get("id")
        thread_ts = body.get("message", {}).get("thread_ts") or body.get("message", {}).get("ts")
        if getattr(cfg, "slack_channel_id", None) and channel_id != cfg.slack_channel_id:
            send_ephemeral_message(
                cfg=cfg,
                channel=channel_id,
                user=user_id,
                text="This action is only available in the membership channel.",
                thread_ts=thread_ts,
            )
            return

        if user_id not in runtime.cache_manager.authorized_users:
            send_ephemeral_message(
                cfg=cfg,
                channel=channel_id,
                user=user_id,
                text="You are not authorized to archive threads.",
                thread_ts=thread_ts,
            )
            return

        if not thread_ts:
            send_ephemeral_message(
                cfg=cfg,
                channel=channel_id,
                user=user_id,
                text="Could not determine the thread to archive.",
            )
            return
        drive_link = None
        with runtime.slack_db_engine.begin() as conn:
            archive_path = archive_thread_events(
                thread_ts=thread_ts,
                slack_conn=conn,
                kos_api_client=runtime.kos_api_client,
            )
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
                    logger.exception("Failed to upload archive to Google Drive.")
            db.insert_audit_event(
                conn,
                action="thread_archived",
                actor_user_id=user_id,
                applicant_user_id=db.get_applicant_user_id_by_thread_ts(conn, thread_ts),
                thread_ts=thread_ts,
                metadata={
                    "archive_path": str(archive_path),
                    "archive_gdrive_url": drive_link,
                },
            )

        archive_message = f"Thread archived to {archive_path}."
        if drive_link:
            archive_message = f"{archive_message} Uploaded to Drive: {drive_link}"
        send_ephemeral_message(
            cfg=cfg,
            channel=channel_id,
            user=user_id,
            text=archive_message,
            thread_ts=thread_ts,
        )
