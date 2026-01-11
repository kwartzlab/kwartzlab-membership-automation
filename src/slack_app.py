import asyncio
import logging
import json
from dataclasses import dataclass
from contextlib import suppress

from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.aiohttp import AsyncSocketModeHandler
from slack_web import get_users, get_user_group, send_ephemeral_message

from config import Config

import db

logger = logging.getLogger(__name__)

@dataclass
class SlackRuntime:
    slack_app: AsyncApp
    socket_handler: AsyncSocketModeHandler
    queue: asyncio.Queue
    slack_engine: db.Engine
    config: Config
    users_cache: dict = None
    authorized_users: set = None

    def __post_init__(self):
        if self.users_cache is None:
            self.users_cache = {}
        if self.authorized_users is None:
            self.authorized_users = set()
            
    def start_tasks(self) -> list[asyncio.Task]:
        return [
            asyncio.create_task(self._consumer()),
            asyncio.create_task(self.socket_handler.start_async()),
            asyncio.create_task(self.update_users_info()),
        ]

    async def _consumer(self):
        while True:
            item = await self.queue.get()
            try:
                await asyncio.to_thread(db.insert_slack_event, self.slack_engine, item)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Failed to archive slack event")
            finally:
                self.queue.task_done()
                
    async def update_users_info(self):
        while True:
            try:
                logger.info("Updating slack user info...")
                users = await asyncio.to_thread(get_users, self.config)
                
                for user in users["members"]:
                    self.users_cache[user["id"]] = user["profile"]["real_name"]
                
                # Reset authorized users to handle deauthorizations
                self.authorized_users = set()
                
                for group_id in self.config.authorized_usergroups:
                    authorized_users = await asyncio.to_thread(get_user_group, self.config, group_id)
                    for user_id in authorized_users.get("users", []):
                        self.authorized_users.add(user_id)
                
                logger.info("Slack user info updated.")
            except asyncio.CancelledError:
                logger.info("User info updater cancelled.")
                break
            except Exception:
                logger.exception("Error updating slack user info")

            await asyncio.sleep(3600)  # Update every hour

def build_slack_runtime(cfg, engine, slack_engine) -> SlackRuntime:
    slack_app = AsyncApp(token=cfg.slack_bot_token)
    socket_handler = AsyncSocketModeHandler(slack_app, cfg.slack_app_token)
    q: asyncio.Queue[dict] = asyncio.Queue()

    runtime = SlackRuntime(slack_app=slack_app, socket_handler=socket_handler, queue=q, slack_engine=slack_engine, config=cfg)


    @slack_app.event("app_mention")
    async def on_app_mention(event, body):
        if event.get("channel") != cfg.slack_channel_id:
            return
        
        command = event.get("text", "").lower().replace(f"<@{body['authorizations'][0]['user_id']}>", "").strip()
        user_id = event.get("user") 

        if user_id not in runtime.authorized_users:
            logger.info("Unauthorized user %s tried to use bot.", user_id)
            send_ephemeral_message(
                cfg,
                channel=event.get("channel"),
                user=user_id,
                message="You are not authorized to use this command. Please contact the membership coordinator or the BoD for access.",
                thread_ts=event.get("thread_ts"),
            )
            return
        logger.info("Authorized user %s used bot.", user_id)
        send_ephemeral_message(
            cfg,
            channel=event.get("channel"),
            user=user_id,
            message="You ARE authorized to use this command.",
            thread_ts=event.get("thread_ts"),
        )


    @slack_app.event("reaction_added")
    async def on_reaction_added(event, body):
        if event.get("item", {}).get("channel") != cfg.slack_channel_id:
            return
        event_data = {
            "thread_ts": None,
            "user_id": event.get("user"),
            "user_name": runtime.users_cache.get(event.get("user"), event.get("user")),  # fallback
            "event": "react_add",
            "message": event.get("reaction"),
            "parent_message": event["item"]["ts"],
            "raw_response": json.dumps(body),
            "timestamp": event.get("event_ts"),
            "applicant_user_id": None,
        }
        await q.put(event_data)

    @slack_app.event("reaction_removed")
    async def on_reaction_removed(event, body):
        if event.get("item", {}).get("channel") != cfg.slack_channel_id:
            return
        event_data = {
            "thread_ts": None,
            "user_id": event.get("user"),
            "user_name": runtime.users_cache.get(event.get("user"), event.get("user")),  # fallback
            "event": "react_remove",
            "message": event.get("reaction"),
            "parent_message": event["item"]["ts"],
            "raw_response": json.dumps(body),
            "timestamp": event.get("event_ts"),
            "applicant_user_id": None,
        }
        await q.put(event_data)

    @slack_app.event("message")
    async def on_message(event, body):
        
        if event.get("subtype") == "bot_message":
            return

        # Optional: restrict to one channel to reduce noise
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
            user_id = message.get("user")  # editor
            
        elif event.get("subtype") == "message_deleted":
            message = event["previous_message"]
            
            event_type = "delete"
            thread_ts = message.get("thread_ts") or event["deleted_ts"]
            parent_message = event.get("deleted_ts")
            text = message.get("text", "")
            user_id = message.get("user")  # editor
            
        else:
            return  # ignore other subtypes

        event_data = {
            "thread_ts": thread_ts,
            "user_id": user_id,
            "user_name": runtime.users_cache.get(user_id, user_id),
            "event": event_type,
            "message": text,
            "parent_message": parent_message,
            "raw_response": json.dumps(body),
            "timestamp": event.get("ts"),
            "applicant_user_id": None,
        }
        await q.put(event_data)


    return runtime
