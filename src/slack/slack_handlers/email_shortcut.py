from services.slack.slack_web import send_ephemeral_message


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
