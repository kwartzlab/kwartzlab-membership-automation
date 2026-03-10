import asyncio
import json
import logging

import services.db as db
import services.mailer as mailer
from utils.names import format_user_full_name
from services.slack.slack_web import post_message_reply, send_ephemeral_message

from slack.slack_handlers.archive import do_archive

logger = logging.getLogger(__name__)

EMAIL_REACTION_CHOICES = {
    "white_check_mark": "acceptance",
    "leftwards_arrow_with_hook": "return_visit",
    "leftward_arrow_with_hook": "return_visit",
    "no_entry_sign": "rejection",
}

EMAIL_PUBLIC_MESSAGES = {
    "acceptance": "{name} has been approved.",
    "return_visit": "Does anyone have any more feedback for {name}? They have been asked to return.",
    "rejection": "{name} has been rejected.",
}

EMAIL_EPHEMERAL_LABELS = {
    "acceptance": "Acceptance",
    "return_visit": "Return",
    "rejection": "Rejection",
}

EMAIL_BUILDERS = {
    "acceptance": mailer.build_acceptance_email,
    "return_visit": mailer.build_return_visit_email,
    "rejection": mailer.build_rejection_email,
}



async def _send_applicant_email(
    *,
    cfg,
    runtime,
    choice: str,
    applicant_user_id: str,
    channel_id: str,
    thread_ts: str,
    actor_user_id: str,
    bcc_self: bool = True,
    signature_name: str | None = None,
    signature_role: str | None = None,
) -> bool:
    user = await asyncio.to_thread(runtime.kos_api_client.get_user, int(applicant_user_id))
    if not user:
        logger.warning("No application found for applicant user ID %s.", applicant_user_id)
        return False

    builder = EMAIL_BUILDERS.get(choice)
    if not builder:
        logger.warning("Invalid email choice: %s.", choice)
        return False

    message = builder(user, bcc_self=bcc_self, signature_name=signature_name, signature_role=signature_role)

    try:
        logger.info("Sending email to user %s", user["email"])
        mailer.send_message(
            service=runtime.mailer,
            user_id=mailer.SENDER_USER_ID,
            message=message,
        )
    except Exception:
        logger.exception("Failed to send email via Gmail API to %s.", user.get("email"))
        return False

    with runtime.slack_db_engine.begin() as conn:
        db.insert_audit_event(
            conn,
            action="email_sent",
            actor_user_id=actor_user_id,
            applicant_user_id=str(applicant_user_id),
            thread_ts=thread_ts,
            metadata={
                "email_type": choice,
                "recipient_email": user.get("email"),
                "channel_id": channel_id,
            },
        )

    send_ephemeral_message(
        cfg=cfg,
        channel=channel_id,
        user=actor_user_id,
        text=f"{EMAIL_EPHEMERAL_LABELS[choice]} email sent to {user.get('email')}.",
        thread_ts=thread_ts,
    )

    post_message_reply(
        cfg=cfg,
        channel=channel_id,
        text=EMAIL_PUBLIC_MESSAGES[choice].format(name=format_user_full_name(user, fallback="Applicant")),
    )

    try:
        await do_archive(cfg=cfg, runtime=runtime, thread_ts=thread_ts, actor_user_id=actor_user_id, channel_id=channel_id)
    except Exception:
        logger.exception("Failed to auto-archive thread %s after email send.", thread_ts)

    return True


async def _handle_reaction_email(event, cfg, runtime):
    reaction = event.get("reaction")
    choice = EMAIL_REACTION_CHOICES.get(reaction)
    if not choice:
        return

    user_id = event.get("user")
    if user_id not in runtime.cache_manager.authorized_users:
        logger.warning("Unauthorized user %s tried to send reaction email.", user_id)
        return

    channel_id = event.get("item", {}).get("channel")
    item_ts = event.get("item", {}).get("ts")
    if not channel_id or not item_ts:
        logger.warning("Reaction event missing channel or ts: %s", event)
        return

    try:
        with runtime.slack_db_engine.connect() as conn:
            thread_ts = db.get_thread_ts(conn, item_ts) or item_ts
            applicant_user_id = db.get_applicant_user_id_by_thread_ts(conn, thread_ts)
            existing = db.has_email_sent(conn, thread_ts, choice)
        if not applicant_user_id:
            logger.warning("No applicant user ID found for reaction email in thread %s.", thread_ts)
            return
        if existing:
            logger.info("Email already sent for thread %s and choice %s; skipping.", thread_ts, choice)
            return

        payload = json.dumps(
            {
                "choice": choice,
                "applicant_user_id": str(applicant_user_id),
                "channel_id": channel_id,
                "thread_ts": thread_ts,
                "actor_user_id": user_id,
            }
        )
        send_ephemeral_message(
            cfg=cfg,
            channel=channel_id,
            user=user_id,
            thread_ts=thread_ts,
            text="Confirm sending email?",
            blocks=[
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"Send *{EMAIL_EPHEMERAL_LABELS[choice]}* email for this applicant?",
                    },
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "action_id": "confirm_reaction_email",
                            "text": {"type": "plain_text", "text": "Send email"},
                            "style": "primary",
                            "value": payload,
                        },
                        {
                            "type": "button",
                            "action_id": "cancel_reaction_email",
                            "text": {"type": "plain_text", "text": "Cancel"},
                            "style": "danger",
                            "value": payload,
                        },
                    ],
                },
            ],
        )
    except Exception:
        logger.exception("Failed to process reaction email.")


def register_reaction_handlers(app, cfg, runtime, queue):
    @app.event("reaction_added")
    async def on_reaction_added(event, body):
        if event.get("item", {}).get("channel") != cfg.slack_channel_id:
            return
        event_data = {
            "thread_ts": None,
            "form_submission_id": None,
            "user_id": event.get("user"),
            "user_name": runtime.cache_manager.users_cache.get(event.get("user"), event.get("user")),
            "event": "react_add",
            "message": event.get("reaction"),
            "parent_message": event["item"]["ts"],
            "raw_response": json.dumps(body),
            "timestamp": event.get("event_ts"),
            "applicant_user_id": None,
        }
        await queue.put(event_data)
        await _handle_reaction_email(event, cfg, runtime)

    @app.event("reaction_removed")
    async def on_reaction_removed(event, body):
        if event.get("item", {}).get("channel") != cfg.slack_channel_id:
            return
        event_data = {
            "thread_ts": None,
            "form_submission_id": None,
            "user_id": event.get("user"),
            "user_name": runtime.cache_manager.users_cache.get(event.get("user"), event.get("user")),
            "event": "react_remove",
            "message": event.get("reaction"),
            "parent_message": event["item"]["ts"],
            "raw_response": json.dumps(body),
            "timestamp": event.get("event_ts"),
            "applicant_user_id": None,
        }
        await queue.put(event_data)
