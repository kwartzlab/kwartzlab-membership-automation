import asyncio
import logging

from services.slack.slack import insert_slack_event

logger = logging.getLogger(__name__)


def _insert_slack_event_threadsafe(slack_db_engine, item):
    with slack_db_engine.begin() as conn:
        insert_slack_event(conn, item)


async def consume_queue(queue: asyncio.Queue, slack_db_engine):
    while True:
        item = await queue.get()
        try:
            await asyncio.to_thread(_insert_slack_event_threadsafe, slack_db_engine, item)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Failed to archive slack event")
        finally:
            queue.task_done()
