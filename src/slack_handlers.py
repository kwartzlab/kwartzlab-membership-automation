import asyncio
import json
import logging

import db
import drive_archive
import services.mailer as mailer
from services.slack.slack_web import post_message_reply, send_ephemeral_message
from thread_archive import archive_thread_events

logger = logging.getLogger(__name__)

EMAIL_REACTION_CHOICES = {
    "white_check_mark": "acceptance",
    "leftwards_arrow_with_hook": "return_visit",
    "leftward_arrow_with_hook": "return_visit",
    "no_entry_sign": "rejection",
}

EMAIL_PUBLIC_MESSAGES = {
    "acceptance": "This application has been approved!",
    "return_visit": "Does anyone have any more feedback for this applicant? They have been asked to return.",
    "rejection": "This application has been rejected.",
}

EMAIL_EPHEMERAL_LABELS = {
    "acceptance": "Acceptance",
    "return_visit": "Return",
    "rejection": "Rejection",
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
    bcc_email: str | None = None,
) -> bool:
    user = await asyncio.to_thread(runtime.kos_api_client.get_user, int(applicant_user_id))
    if not user:
        logger.warning("No application found for applicant user ID %s.", applicant_user_id)
        return False

    if choice == "acceptance":
        message = mailer.build_acceptance_email(user, bcc=bcc_email)
    elif choice == "return_visit":
        message = mailer.build_return_visit_email(user, bcc=bcc_email)
    elif choice == "rejection":
        message = mailer.build_rejection_email(user, bcc=bcc_email)
    else:
        logger.warning("Invalid email choice: %s.", choice)
        return False

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
        text=f"{EMAIL_EPHEMERAL_LABELS[choice]} email sent.",
        thread_ts=thread_ts,
    )

    post_message_reply(
        cfg=cfg,
        channel=channel_id,
        thread_ts=thread_ts,
        text=EMAIL_PUBLIC_MESSAGES[choice],
        reply_broadcast=(choice == "return_visit"),
    )
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

        await _send_applicant_email(
            cfg=cfg,
            runtime=runtime,
            choice=choice,
            applicant_user_id=applicant_user_id,
            channel_id=channel_id,
            thread_ts=thread_ts,
            actor_user_id=user_id,
        )
    except Exception:
        logger.exception("Failed to process reaction email.")


def register_app_mention_handler(app, cfg, runtime):
    @app.event("app_mention")
    async def on_app_mention(event, body):
        if event.get("channel") != cfg.slack_channel_id:
            return

        command = event.get("text", "").lower().replace(f"<@{body['authorizations'][0]['user_id']}>", "").strip()
        user_id = event.get("user")

        if user_id not in runtime.cache_manager.authorized_users:
            logger.warning("Unauthorized user %s tried to use bot.", user_id)
            return
        logger.debug("Authorized user %s used command %s.", user_id, command)


def register_reaction_handlers(app, cfg, runtime, queue):
    @app.event("reaction_added")
    async def on_reaction_added(event, body):
        if event.get("item", {}).get("channel") != cfg.slack_channel_id:
            return
        event_data = {
            "thread_ts": None,
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


def register_message_handler(app, cfg, runtime, queue):
    @app.event("message")
    async def on_message(event, body):
        if event.get("subtype") == "bot_message":
            return

        if getattr(cfg, "slack_channel_id", None):
            if event.get("channel") != cfg.slack_channel_id:
                return

        event_data = {}
        if event.get("subtype") in (None, "message_replied"):
            event_type = "post" if not event.get("thread_ts") else "reply"
            thread_ts = event.get("thread_ts") or event.get("ts")
            parent_message = event.get("thread_ts") if event.get("thread_ts") else None
            text = event.get("text", "")
            user_id = event.get("user")

        elif event.get("subtype") == "message_changed":
            message = event["message"]

            event_type = "edit"
            thread_ts = message.get("thread_ts") or message["ts"]
            parent_message = message["ts"]
            text = message.get("text", "")
            user_id = message.get("user")

        elif event.get("subtype") == "message_deleted":
            message = event["previous_message"]

            event_type = "delete"
            thread_ts = message.get("thread_ts") or event["deleted_ts"]
            parent_message = event.get("deleted_ts")
            text = message.get("text", "")
            user_id = message.get("user")

        else:
            return

        event_data = {
            "thread_ts": thread_ts,
            "user_id": user_id,
            "user_name": runtime.cache_manager.users_cache.get(user_id, user_id),
            "event": event_type,
            "message": text,
            "parent_message": parent_message,
            "raw_response": json.dumps(body),
            "timestamp": event.get("ts"),
            "applicant_user_id": None,
        }
        await queue.put(event_data)


def register_email_shortcut_handler(app, cfg, runtime):
    @app.shortcut("email_applicant")
    async def handle_shortcuts(ack, body, logger):
        await ack()  # REQUIRED for shortcuts

        user = body["user"]["id"]
        channel = body["channel"]["id"]
        message_ts = body["message"]["ts"]
        thread_ts = body["message"].get("thread_ts", message_ts)

        if user not in runtime.cache_manager.authorized_users:
            send_ephemeral_message(
                cfg=cfg,
                channel=channel,
                user=user,
                text="You’re not allowed to do this.",
                thread_ts=thread_ts,
            )
            return

        resp = send_ephemeral_message(
            cfg=cfg,
            channel=channel,
            user=user,
            text="Please choose the type of email to send:",
            blocks=[
                {"type": "section", "text": {"type": "mrkdwn", "text": f"*<@{user}> Choose an option:*"}},
                {
                    "type": "input",
                    "block_id": "choice_block",
                    "label": {"type": "plain_text", "text": "Email type:"},
                    "element": {
                        "type": "static_select",
                        "action_id": "choice_select",
                        "placeholder": {"type": "plain_text", "text": "Pick one…"},
                        "options": [
                            {
                                "text": {"type": "plain_text", "text": ":white_check_mark: - Acceptance  "},
                                "value": "acceptance",
                            },
                            {
                                "text": {"type": "plain_text", "text": ":leftwards_arrow_with_hook: - Return visit"},
                                "value": "return_visit",
                            },
                            {
                                "text": {"type": "plain_text", "text": ":no_entry_sign: - Rejection"},
                                "value": "rejection",
                            },
                        ],
                    },
                },
                {
                    "type": "input",
                    "optional": True,
                    "block_id": "bcc_block",
                    "label": {"type": "plain_text", "text": "BCC"},
                    "element": {
                        "type": "checkboxes",
                        "action_id": "bcc_self",
                        "options": [
                            {"text": {"type": "plain_text", "text": "BCC membership@kwartzlab.ca"}, "value": "bcc_self"}
                        ],
                        "initial_options": [
                            {"text": {"type": "plain_text", "text": "BCC membership@kwartzlab.ca"}, "value": "bcc_self"}
                        ],
                    },
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Confirm"},
                            "style": "primary",
                            "action_id": "confirm_submit",
                            "value": "confirm",
                        },
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Cancel"},
                            "style": "danger",
                            "action_id": "email_cancel",
                            "value": "cancel",
                        },
                    ],
                },
            ],
            thread_ts=thread_ts,
        )

        logger.debug("Shortcut response sent for user %s: %s", user, resp)


def register_archive_shortcut_handler(app, cfg, runtime):
    @app.shortcut("archive_thread")
    async def handle_archive_shortcut(ack, body, logger):
        await ack()

        user_id = body.get("user", {}).get("id")
        if user_id not in runtime.cache_manager.authorized_users:
            send_ephemeral_message(
                cfg=cfg,
                channel=body.get("channel", {}).get("id"),
                user=user_id,
                text="You are not authorized to archive threads.",
                thread_ts=body.get("message", {}).get("thread_ts") or body.get("message", {}).get("ts"),
            )
            return

        thread_ts = body.get("message", {}).get("thread_ts") or body.get("message", {}).get("ts")
        if not thread_ts:
            send_ephemeral_message(
                cfg=cfg,
                channel=body.get("channel", {}).get("id"),
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
            channel=body.get("channel", {}).get("id"),
            user=user_id,
            text=archive_message,
            thread_ts=thread_ts,
        )


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
            with runtime.slack_db_engine.connect() as conn:
                applicant_user_id = db.get_applicant_user_id_by_thread_ts(conn, body["container"]["thread_ts"])
            if not applicant_user_id:
                raise ValueError("No applicant user ID found for this message.")

            channel_id = body.get("channel", {}).get("id")
            thread_ts = body.get("container", {}).get("thread_ts")
            user_id = body.get("user", {}).get("id")
            if not channel_id or not thread_ts or not user_id:
                raise ValueError("Missing channel_id, thread_ts, or user_id.")

            email_sent = await _send_applicant_email(
                cfg=cfg,
                runtime=runtime,
                choice=choice,
                applicant_user_id=str(applicant_user_id),
                channel_id=channel_id,
                thread_ts=thread_ts,
                actor_user_id=user_id,
                bcc_email=bcc_email,
            )

        except Exception as e:
            logger.exception("Failed to send email.")
            raise e

        # post_message_reply(
        #         cfg=cfg,
        #         channel=body["channel"]["id"],
        #         thread_ts=body["container"]["thread_ts"],
        #         message="Email sent successfully.",
        #         reply_broadcast=True
        #     )
        try:
            await respond(delete_original=True)
            return
        except Exception as e:
            await respond(replace_original=True, text=f"Error processing: {e}", blocks=[])

        await respond(replace_original=True, text="Cancelled.", blocks=[])

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
            pass

        await respond(replace_original=True, text="Cancelled.", blocks=[])


def register_modal_handler(app, cfg, runtime):
    @app.action("view_application_questions")
    async def handle_view_questions(ack, body, client, logger):
        await ack()

        try:
            thread_ts = body.get("message", {}).get("thread_ts") or body.get("message", {}).get("ts")
            if not thread_ts:
                # Fallback: try container message
                thread_ts = body.get("container", {}).get("message_ts")

            if not thread_ts:
                logger.warning("No thread_ts/ts found in action body.")
                return

            with runtime.slack_db_engine.connect() as conn:
                modal = db.get_modal_blocks_payload_by_thread_ts(conn, thread_ts)

            if not modal:
                await client.views_open(
                    trigger_id=body["trigger_id"],
                    view={
                        "type": "modal",
                        "title": {"type": "plain_text", "text": "Application"},
                        "close": {"type": "plain_text", "text": "Close"},
                        "blocks": [
                            {
                                "type": "section",
                                "text": {"type": "mrkdwn", "text": "Couldn’t find application data for this thread."},
                            }
                        ],
                    },
                )
                return

            await client.views_open(trigger_id=body["trigger_id"], view=modal)

        except Exception as e:
            logger.exception("Failed to open questions modal: %s", e)
            # Avoid leaking details to users; just log server-side.
            try:
                await client.views_open(
                    trigger_id=body["trigger_id"],
                    view={
                        "type": "modal",
                        "title": {"type": "plain_text", "text": "Error"},
                        "close": {"type": "plain_text", "text": "Close"},
                        "blocks": [
                            {
                                "type": "section",
                                "text": {"type": "mrkdwn", "text": "Something went wrong opening the modal."},
                            }
                        ],
                    },
                )
            except Exception:
                pass
