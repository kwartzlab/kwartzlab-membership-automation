import logging

import services.db as db
import services.mailer as mailer

from .reactions import _send_applicant_email

logger = logging.getLogger(__name__)


def register_email_actions(app, cfg, runtime):
    @app.action("confirm_submit")
    async def handle_send_email(ack, body, logger, respond):
        await ack()
        logger.debug(
            "Email action received (user=%s, action=%s).",
            body.get("user", {}).get("id"),
            body.get("actions", [{}])[0].get("action_id"),
        )
        try:
            choice = body["state"]["values"]["choice_block"]["choice_select"]["selected_option"]["value"]
            bcc_selected = body["state"]["values"].get("bcc_block", {}).get("bcc_self", {}).get("selected_options", [])
            bcc_email = mailer.MEMBERSHIP_GROUP_FROM_EMAIL if bcc_selected else None
            channel_id = body.get("channel", {}).get("id")
            thread_ts = body.get("container", {}).get("thread_ts")
            user_id = body.get("user", {}).get("id")
            if not channel_id or not thread_ts or not user_id:
                raise ValueError("Missing channel_id, thread_ts, or user_id.")

            with runtime.slack_db_engine.connect() as conn:
                applicant_user_id = db.get_applicant_user_id_by_thread_ts(conn, thread_ts)
                if not applicant_user_id:
                    raise ValueError("No applicant user ID found for this message.")
                if db.has_email_sent(conn, thread_ts, choice):
                    await respond(
                        replace_original=True,
                        text="That email has already been sent for this thread.",
                        blocks=[],
                    )
                    return

            await _send_applicant_email(
                cfg=cfg,
                runtime=runtime,
                choice=choice,
                applicant_user_id=str(applicant_user_id),
                channel_id=channel_id,
                thread_ts=thread_ts,
                actor_user_id=user_id,
                bcc_email=bcc_email,
            )

        except Exception:
            logger.exception("Failed to send email.")
            await respond(
                replace_original=True,
                text="Error sending email. Please try again.",
                blocks=[],
            )
            return

        try:
            await respond(delete_original=True)
            return
        except Exception as exc:
            await respond(replace_original=True, text=f"Email sent, but could not clear this prompt: {exc}", blocks=[])

    @app.action("choice_select")
    async def handle_some_action(ack, body, logger):
        await ack()
        logger.debug(
            "Choice select action received (user=%s).",
            body.get("user", {}).get("id"),
        )

    @app.action("email_cancel")
    async def cancel(ack, respond):
        await ack()
        try:
            await respond(delete_original=True)
            return
        except Exception:
            logger.debug("Failed to delete original message on cancel.")

        await respond(replace_original=True, text="Cancelled.", blocks=[])
