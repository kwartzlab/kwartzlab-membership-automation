import asyncio
import logging
from dataclasses import dataclass
from contextlib import suppress

from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.aiohttp import AsyncSocketModeHandler

import db

logger = logging.getLogger(__name__)

@dataclass
class SlackRuntime:
    slack_app: AsyncApp
    socket_handler: AsyncSocketModeHandler
    queue: asyncio.Queue

    def start_tasks(self) -> list[asyncio.Task]:
        return [
            asyncio.create_task(self._consumer()),
            asyncio.create_task(self.socket_handler.start_async()),
        ]

    async def _consumer(self):
        while True:
            item = await self.queue.get()
            try:
                await asyncio.to_thread(db.archive_slack_message, item)  # you implement; or pass engine in item
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Failed to archive slack message")
            finally:
                self.queue.task_done()

def build_slack_runtime(cfg, engine) -> SlackRuntime:
    slack_app = AsyncApp(token=cfg.slack_bot_token)
    socket_handler = AsyncSocketModeHandler(slack_app, cfg.slack_app_token)
    q: asyncio.Queue[dict] = asyncio.Queue()

    # Register handlers here so they can close over cfg/engine/q
    @slack_app.event("message")
    async def debug(event, logger):
        print("EVENT", event)
    
    @slack_app.event("message")
    async def on_message(event, body):
        
        logger.info("Message received %s", body)
        
        
        if event.get("subtype") == "bot_message":
            return

        logger.info("Message received %s", body)

        # Optional: restrict to one channel to reduce noise
        if getattr(cfg, "slack_channel_id", None):
            if event.get("channel") != cfg.slack_channel_id:
                return

        # Enqueue minimal fields; DB work happens in consumer (threaded)
        await q.put({
            "engine": engine,                 # easiest way to get engine into archive call
            "channel": event.get("channel"),
            "user": event.get("user"),
            "text": event.get("text", ""),
            "ts": event.get("ts"),
            "thread_ts": event.get("thread_ts"),
        })

    return SlackRuntime(slack_app=slack_app, socket_handler=socket_handler, queue=q)