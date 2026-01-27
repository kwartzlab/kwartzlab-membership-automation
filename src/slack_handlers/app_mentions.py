import logging

logger = logging.getLogger(__name__)


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

