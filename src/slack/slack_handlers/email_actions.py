import json
import logging

import services.db as db
from services.slack.slack_web import send_ephemeral_message
from slack.slack_handlers.reactions import _send_applicant_email

logger = logging.getLogger(__name__)


def register_email_actions(app, cfg, runtime):
    @app.view("email_applicant_modal")
    async def handle_email_applicant_modal(ack, body, logger):
        await ack()
        channel_id = None
        thread_ts = None
        user_id = None
        try:
            view = body.get("view", {})
            state_values = view.get("state", {}).get("values", {})
            choice = state_values["choice_block"]["choice_select"]["selected_option"]["value"]
            signature_name = state_values.get("signature_name_block", {}).get("signature_name_input", {}).get("value")
            signature_role = state_values.get("signature_role_block", {}).get("signature_role_input", {}).get("value")
            bcc_selected = state_values.get("bcc_block", {}).get("bcc_self", {}).get("selected_options", [])
            bcc_self = bool(bcc_selected)

            metadata = json.loads(view.get("private_metadata", "{}"))
            channel_id = metadata.get("channel_id")
            thread_ts = metadata.get("thread_ts")
            actor_user_id = metadata.get("user_id")
            user_id = body.get("user", {}).get("id")

            if not channel_id or not thread_ts or not actor_user_id or not user_id:
                raise ValueError("Missing modal metadata.")
            if channel_id != cfg.slack_channel_id:
                send_ephemeral_message(
                    cfg=cfg,
                    channel=channel_id,
                    user=user_id,
                    thread_ts=thread_ts,
                    text="This action is only available in the membership channel.",
                )
                return
            if user_id != actor_user_id:
                send_ephemeral_message(
                    cfg=cfg,
                    channel=channel_id,
                    user=user_id,
                    thread_ts=thread_ts,
                    text="This action isn’t for you.",
                )
                return
            if user_id not in runtime.cache_manager.authorized_users:
                send_ephemeral_message(
                    cfg=cfg,
                    channel=channel_id,
                    user=user_id,
                    thread_ts=thread_ts,
                    text="You’re not authorized to send emails.",
                )
                return

            with runtime.slack_db_engine.connect() as conn:
                applicant_user_id = db.get_applicant_user_id_by_thread_ts(conn, thread_ts)
                if not applicant_user_id:
                    raise ValueError("No applicant user ID found for this thread.")
                if db.has_email_sent(conn, thread_ts, choice):
                    send_ephemeral_message(
                        cfg=cfg,
                        channel=channel_id,
                        user=user_id,
                        thread_ts=thread_ts,
                        text="That email has already been sent for this thread.",
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
                bcc_self=bcc_self,
                signature_name=signature_name,
                signature_role=signature_role,
            )
        except Exception:
            logger.exception("Failed to send email via modal.")
            if channel_id and thread_ts and user_id:
                send_ephemeral_message(
                    cfg=cfg,
                    channel=channel_id,
                    user=user_id,
                    thread_ts=thread_ts,
                    text="Error sending email. Please try again.",
                )

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
            bcc_self = bool(bcc_selected)
            channel_id = body.get("channel", {}).get("id")
            thread_ts = body.get("container", {}).get("thread_ts")
            user_id = body.get("user", {}).get("id")
            if not channel_id or not thread_ts or not user_id:
                raise ValueError("Missing channel_id, thread_ts, or user_id.")
            if channel_id != cfg.slack_channel_id:
                await respond(
                    replace_original=True,
                    text="This action is only available in the membership channel.",
                    blocks=[],
                )
                return

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
                bcc_self=bcc_self,
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

    @app.action("confirm_reaction_email")
    async def confirm_reaction_email(ack, body, respond, logger):
        await ack()
        try:
            action = body.get("actions", [{}])[0]
            payload = json.loads(action.get("value", "{}"))
            choice = payload.get("choice")
            applicant_user_id = payload.get("applicant_user_id")
            channel_id = payload.get("channel_id")
            thread_ts = payload.get("thread_ts")
            actor_user_id = payload.get("actor_user_id")
            user_id = body.get("user", {}).get("id")

            if not all([choice, applicant_user_id, channel_id, thread_ts, actor_user_id, user_id]):
                raise ValueError("Missing confirmation details.")
            if channel_id != cfg.slack_channel_id:
                await respond(
                    replace_original=True, text="This action is only available in the membership channel.", blocks=[]
                )
                return
            if user_id != actor_user_id:
                await respond(replace_original=True, text="This confirmation isn’t for you.", blocks=[])
                return
            if user_id not in runtime.cache_manager.authorized_users:
                await respond(replace_original=True, text="You’re not authorized to send emails.", blocks=[])
                return

            with runtime.slack_db_engine.connect() as conn:
                if db.has_email_sent(conn, thread_ts, choice):
                    await respond(replace_original=True, text="That email was already sent.", blocks=[])
                    return

            await _send_applicant_email(
                cfg=cfg,
                runtime=runtime,
                choice=choice,
                applicant_user_id=str(applicant_user_id),
                channel_id=channel_id,
                thread_ts=thread_ts,
                actor_user_id=user_id,
            )

            await respond(delete_original=True)
        except Exception:
            logger.exception("Failed to confirm reaction email.")
            await respond(replace_original=True, text="Error sending email.", blocks=[])

    @app.action("cancel_reaction_email")
    async def cancel_reaction_email(ack, respond):
        await ack()
        try:
            await respond(delete_original=True)
            return
        except Exception:
            await respond(replace_original=True, text="Cancelled.", blocks=[])
