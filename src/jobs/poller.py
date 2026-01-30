import asyncio
import logging

from jobs import interviews

logger = logging.getLogger(__name__)


def _process_one_threadsafe(kos_api_client, slack_engine, cfg, outbox_id: int | None = None):
    with slack_engine.begin() as slack_conn:
        return interviews.process_one(kos_api_client, slack_conn, cfg, outbox_id=outbox_id)


async def poller_loop(cfg, kos_api_client, slack_engine):
    while True:
        # Inner loop to process all available outbox items
        while True:
            try:
                logger.info("Checking for outbox items.")
                result = await asyncio.to_thread(_process_one_threadsafe, kos_api_client, slack_engine, cfg)
                if result is None:
                    logger.info("No outbox items to process.")
                    break
            except asyncio.CancelledError:
                logger.info("Poller cancelled.")
                raise
            except Exception:
                logger.exception("Error processing outbox item")

            await asyncio.sleep(5)  # brief pause between processing items

        await asyncio.sleep(cfg.poll_interval_seconds)
