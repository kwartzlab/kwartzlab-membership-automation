import asyncio
import logging

from jobs import interviews

logger = logging.getLogger(__name__)


async def poller_loop(cfg, kos_api_client, slack_engine):
    while True:
        # Inner loop to process all available outbox items
        while True:
            try:
                logger.debug("Checking for missed messages.")
                with slack_engine.begin() as slack_conn:
                    result = await asyncio.to_thread(interviews.process_one, kos_api_client, slack_conn, cfg)
                    if result is None:
                        logger.debug("No outbox items to process.")
                        break
            except asyncio.CancelledError:
                logger.info("Poller cancelled.")
                break
            except Exception:
                logger.exception("Error processing outbox item")

            await asyncio.sleep(5)  # brief pause between processing items

        await asyncio.sleep(cfg.poll_interval_seconds)
