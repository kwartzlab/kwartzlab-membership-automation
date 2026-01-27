import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from slack_bolt.adapter.socket_mode.aiohttp import AsyncSocketModeHandler
from slack_bolt.async_app import AsyncApp
from sqlalchemy.engine import Engine

import services.kos_api as kos_api
from slack import archiver as slack_archiver
from slack import slack_handlers
from core.config import Config
from services.slack.slack_web import get_user_group, get_users

logger = logging.getLogger(__name__)


@dataclass
class UserCacheManager:
    users_cache: dict = None
    authorized_users: set = None
    config: Config = None

    def __post_init__(self):
        if self.users_cache is None:
            self.users_cache = {}
        if self.authorized_users is None:
            self.authorized_users = set()

    async def update_users_info(self):
        while True:
            try:
                logger.debug("Updating slack user info.")
                users = await asyncio.to_thread(get_users, self.config)

                for user in users["members"]:
                    self.users_cache[user["id"]] = user["profile"]["real_name"]

                # Reset authorized users to handle deauthorizations
                self.authorized_users = set()

                for group_id in self.config.authorized_usergroups:
                    authorized_users = await asyncio.to_thread(get_user_group, self.config, group_id)
                    for user_id in authorized_users.get("users", []):
                        self.authorized_users.add(user_id)

                logger.debug("Slack user info updated.")
            except asyncio.CancelledError:
                logger.info("User info updater cancelled.")
                break
            except Exception:
                logger.exception("Error updating slack user info")

            await asyncio.sleep(3600)  # Update every hour


@dataclass
class SlackRuntime:
    slack_app: AsyncApp
    socket_handler: AsyncSocketModeHandler
    queue: asyncio.Queue
    slack_db_engine: Engine
    kos_api_client: kos_api.KosApiClient
    config: Config
    cache_manager: UserCacheManager = None
    mailer: Any = None

    def __post_init__(self):
        if self.cache_manager is None:
            self.cache_manager = UserCacheManager(config=self.config)

    def start_tasks(self) -> list[asyncio.Task]:
        return [
            asyncio.create_task(slack_archiver.consume_queue(self.queue, self.slack_db_engine)),
            asyncio.create_task(self.socket_handler.start_async()),
            asyncio.create_task(self.cache_manager.update_users_info()),
        ]


def build_slack_runtime(cfg, kos_api_client, slack_db_engine, mailer) -> SlackRuntime:
    slack_app = AsyncApp(token=cfg.slack_bot_token)
    logging.getLogger("slack_bolt.AsyncApp").setLevel(logging.WARNING)
    socket_handler = AsyncSocketModeHandler(slack_app, cfg.slack_app_token)
    q: asyncio.Queue[dict] = asyncio.Queue()

    runtime = SlackRuntime(
        slack_app=slack_app,
        socket_handler=socket_handler,
        queue=q,
        slack_db_engine=slack_db_engine,
        config=cfg,
        kos_api_client=kos_api_client,
        mailer=mailer,
    )

    slack_handlers.register_app_mention_handler(slack_app, cfg, runtime)
    slack_handlers.register_reaction_handlers(slack_app, cfg, runtime, q)
    slack_handlers.register_message_handler(slack_app, cfg, runtime, q)
    slack_handlers.register_email_shortcut_handler(slack_app, cfg, runtime)
    slack_handlers.register_archive_shortcut_handler(slack_app, cfg, runtime)
    slack_handlers.register_email_actions(slack_app, cfg, runtime)
    slack_handlers.register_modal_handler(slack_app, cfg, runtime)
    return runtime
