import logging

from .onboarding_dm import handle_onboarding_dm_command, onboarding_help_text

logger = logging.getLogger(__name__)


def register_dm_handler(app, cfg, runtime):
    @app.event("message")
    async def on_dm_message(event, say):
        if event.get("subtype"):
            return
        if event.get("channel_type") != "im":
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
            await say(f"DM workflows:\n{onboarding_help_text()}")
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

        await say("Unknown DM command. Use `help` to see available commands.")
