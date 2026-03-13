import logging

from slack.slack_handlers.audit_dm import audit_dm_help_text, handle_audit_dm_command
from slack.slack_handlers.email_dm import email_dm_help_text, handle_email_dm_command
from slack.slack_handlers.onboarding_dm import handle_onboarding_dm_command, onboarding_help_text
from slack.slack_handlers.utils import is_message_channel_type

logger = logging.getLogger(__name__)


def register_dm_handler(app, cfg, runtime):
    @app.event("message", matchers=[is_message_channel_type("im")])
    async def on_dm_message(event, say):
        if event.get("subtype"):
            return

        user_id = str(event.get("user") or "")
        text = str(event.get("text") or "").strip()
        if not text:
            return

        if user_id not in runtime.cache_manager.authorized_users:
            await say("You are not authorized to run DM workflows.")
            return

        lowered = text.lower()
        if lowered in {"help", "dm help"}:
            await say(f"DM workflows:\n{onboarding_help_text()}\n\n{email_dm_help_text()}\n\n{audit_dm_help_text()}")
            return

        if lowered.startswith("onboard"):
            handled = await handle_onboarding_dm_command(
                text,
                user_id=user_id,
                say=say,
                cfg=cfg,
                runtime=runtime,
            )
            if handled:
                return

        if (
            lowered.startswith("check email")
            or lowered.startswith("create email")
            or lowered.startswith("reset password")
            or lowered.startswith("reset email")
        ):
            handled = await handle_email_dm_command(
                text,
                user_id=user_id,
                say=say,
                cfg=cfg,
                runtime=runtime,
            )
            if handled:
                return

        if lowered.startswith("audit"):
            handled = await handle_audit_dm_command(
                text,
                user_id=user_id,
                say=say,
                cfg=cfg,
                runtime=runtime,
            )
            if handled:
                return

        await say("Unknown DM command. Use `help` to see available commands.")
