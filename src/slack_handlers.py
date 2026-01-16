import json
import logging
import mailer
from slack_web import send_ephemeral_message, post_message_reply
import db

logger = logging.getLogger(__name__)

def register_app_mention_handler(app, cfg, runtime):
    @app.event("app_mention")
    async def on_app_mention(event, body):
        if event.get("channel") != cfg.slack_channel_id:
            return
        
        command = event.get("text", "").lower().replace(f"<@{body['authorizations'][0]['user_id']}>", "").strip()
        user_id = event.get("user") 

        if user_id not in runtime.cache_manager.authorized_users:
            logger.info("Unauthorized user %s tried to use bot.", user_id)
            send_ephemeral_message(
                cfg,
                channel=event.get("channel"),
                user=user_id,
                text="You are not authorized to use this command. Please contact the membership coordinator or the BoD for access.",
                thread_ts=event.get("thread_ts"),
            )
            return
        logger.info("Authorized user %s used bot.", user_id)
        send_ephemeral_message(
            cfg,
            channel=event.get("channel"),
            user=user_id,
            text="You ARE authorized to use this command.",
            thread_ts=event.get("thread_ts"),
        )

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
        await ack()   # REQUIRED for shortcuts

        user = body["user"]["id"]
        channel = body["channel"]["id"]
        message_ts = body["message"]["ts"]
        thread_ts = body["message"].get("thread_ts", message_ts)

        if user not in runtime.cache_manager.authorized_users:
            send_ephemeral_message(
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
            text=f"Please choose the type of email to send and provide signature details:",
            blocks=[
                {
                    "type": "section",
                    "text": { "type": "mrkdwn", "text": f"*<@{user}> Choose an option and enter signature details:*" }
                },
                {
                    "type": "input",
                    "block_id": "choice_block",
                    "label": { "type": "plain_text", "text": "Email type:" },
                    "element": {
                    "type": "static_select",
                    "action_id": "choice_select",
                    "placeholder": { "type": "plain_text", "text": "Pick one…" },
                    "options": [
                        { "text": { "type": "plain_text", "text": ":white_check_mark: - Acceptance  " }, "value": "acceptance" },
                        { "text": { "type": "plain_text", "text": ":leftwards_arrow_with_hook: - Return visit" }, "value": "return_visit" },
                        { "text": { "type": "plain_text", "text": ":no_entry_sign: - Rejection" }, "value": "rejection" }
                    ]
                    }
                },
                {
                    "type": "input",
                    "block_id": "sig_name_block",
                    "label": { "type": "plain_text", "text": "Signature name" },
                    "element": {
                        "type": "plain_text_input",
                        "action_id": "sig_name",
                        "initial_value": runtime.cache_manager.users_cache.get(user, ""),
                        "placeholder": { "type": "plain_text", "text": "e.g., Alex Chen" }
                    }
                },
                {
                    "type": "input",
                    "optional": True,
                    "block_id": "sig_role_block",
                    "label": { "type": "plain_text", "text": "Signature role" },
                    "element": {
                        "type": "plain_text_input",
                        "action_id": "sig_role",
                        "placeholder": { "type": "plain_text", "text": "e.g., Membership Coordinator" }
                    }
                },
                {
                    "type": "actions",
                    "elements": [
                    {
                        "type": "button",
                        "text": { "type": "plain_text", "text": "Confirm" },
                        "style": "primary",
                        "action_id": "confirm_submit",
                        "value": "confirm"
                    },
                    {
                        "type": "button",
                        "text": { "type": "plain_text", "text": "Cancel" },
                        "style": "danger",
                        "action_id": "email_cancel",
                        "value": "cancel"
                    }
                    ]
                }
            ],
            thread_ts=thread_ts,
        )
        
        logger.info("Shortcut response: %s", resp)

def register_email_actions(app, cfg, runtime):
    
    @app.action("confirm_submit")
    async def handle_send_email(ack, body, logger, respond):
        await ack()
        logger.info(body)
        try:
            choice = body["state"]["values"]["choice_block"]["choice_select"]["selected_option"]["value"]
            sig_name = body["state"]["values"]["sig_name_block"]["sig_name"]["value"]
            sig_role = body["state"]["values"]["sig_role_block"].get("sig_role", {}).get("value", "")
            with runtime.slack_db_engine.connect() as conn:
                applicant_user_id = db.get_applicant_user_id_by_thread_ts(conn, body["container"]["thread_ts"])
            if not applicant_user_id:
                raise ValueError("No applicant user ID found for this message.")

            with runtime.kos_db_engine.begin() as conn:
                user = db.get_user_by_id(conn, int(applicant_user_id))                    
                if not user:
                    raise ValueError("No application found for applicant user ID.")
                        
            gmail_service = runtime.mailer
            

            email_sent = False
            if choice == "acceptance":
                message = mailer.build_acceptance_email(user)
            elif choice == "return_visit":
                message = mailer.build_return_visit_email(user)
            elif choice == "rejection":
                message = mailer.build_rejection_email(user)
            else:
                raise ValueError("Invalid email choice.")
            
            try:
                logger.info("Sending email to user %s", user["email"])
                mailer.send_message(
                    service=gmail_service,
                    user_id=mailer.SENDER_USER_ID,
                    message=message
                )
            except Exception as e:
                logger.error("Failed to send email via Gmail API: %s", e)
            
        except Exception as e:
            logger.error("Failed to send email: %s", e)
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
        except Exception:
            pass

        await respond(
            replace_original=True,
            text="Cancelled.",
            blocks=[]
        )

    @app.action("choice_select")
    async def handle_some_action(ack, body, logger):
        await ack()
        logger.info(body)

    @app.action("email_cancel")
    async def cancel(ack, respond):
        await ack()
        try:
            await respond(delete_original=True)
            return
        except Exception:
            pass

        await respond(
            replace_original=True,
            text="Cancelled.",
            blocks=[]
        )
        
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
                            {"type": "section", "text": {"type": "mrkdwn", "text": "Something went wrong opening the modal."}}
                        ],
                    },
                )
            except Exception:
                pass