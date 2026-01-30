import json

from services import mailer
from services.slack.slack_web import send_ephemeral_message


def register_email_shortcut_handler(app, cfg, runtime):
    @app.shortcut("email_applicant")
    async def handle_shortcuts(ack, body, client, logger):
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

        private_metadata = json.dumps({"channel_id": channel, "thread_ts": thread_ts, "user_id": user})
        signature_name = runtime.cache_manager.users_cache.get(user, "")
        signature_role = mailer.DEFAULT_SIGNATURE_ROLE
        view = {
            "type": "modal",
            "callback_id": "email_applicant_modal",
            "title": {"type": "plain_text", "text": "Email applicant"},
            "submit": {"type": "plain_text", "text": "Send"},
            "close": {"type": "plain_text", "text": "Cancel"},
            "private_metadata": private_metadata,
            "blocks": [
                {
                    "type": "input",
                    "block_id": "choice_block",
                    "label": {"type": "plain_text", "text": "Email type"},
                    "element": {
                        "type": "static_select",
                        "action_id": "choice_select",
                        "placeholder": {"type": "plain_text", "text": "Pick one…"},
                        "options": [
                            {
                                "text": {"type": "plain_text", "text": ":white_check_mark: Acceptance"},
                                "value": "acceptance",
                            },
                            {
                                "text": {"type": "plain_text", "text": ":leftwards_arrow_with_hook: Return visit"},
                                "value": "return_visit",
                            },
                            {
                                "text": {"type": "plain_text", "text": ":no_entry_sign: Rejection"},
                                "value": "rejection",
                            },
                        ],
                    },
                },
                {
                    "type": "input",
                    "optional": True,
                    "block_id": "signature_name_block",
                    "label": {"type": "plain_text", "text": "Signature name"},
                    "element": {
                        "type": "plain_text_input",
                        "action_id": "signature_name_input",
                        "placeholder": {"type": "plain_text", "text": "Membership Team"},
                        "initial_value": signature_name,
                    },
                },
                {
                    "type": "input",
                    "optional": True,
                    "block_id": "signature_role_block",
                    "label": {"type": "plain_text", "text": "Signature role"},
                    "element": {
                        "type": "plain_text_input",
                        "action_id": "signature_role_input",
                        "placeholder": {"type": "plain_text", "text": "e.g., Membership Coordinator"},
                        "initial_value": signature_role,
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
            ],
        }

        await client.views_open(trigger_id=body["trigger_id"], view=view)
        logger.debug("Email modal opened for user %s.", user)
