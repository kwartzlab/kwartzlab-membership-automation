import asyncio
import logging
import db

logger = logging.getLogger(__name__)

async def consume_queue(queue: asyncio.Queue, slack_db_engine):
    while True:
        item = await queue.get()
        try:
            await asyncio.to_thread(db.insert_slack_event, slack_db_engine, item)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Failed to archive slack event")
        finally:
            queue.task_done()