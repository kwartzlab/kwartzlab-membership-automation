import asyncio
import logging

from services.slack import insert_slack_event

logger = logging.getLogger(__name__)

async def consume_queue(queue: asyncio.Queue, slack_db_engine):
    while True:
        item = await queue.get()
        try:
            with slack_db_engine.begin() as conn:
                await asyncio.to_thread(insert_slack_event, conn, item)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Failed to archive slack event")
        finally:
            queue.task_done()