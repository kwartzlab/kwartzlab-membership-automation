import asyncio
import logging

import services.interviews as interviews

logger = logging.getLogger(__name__)

async def poller_loop(cfg, kos_api_client, slack_engine):
    while True:
        try:
            logger.info("Checking for missed messages...")
            with slack_engine.begin() as slack_conn:
                await asyncio.to_thread(interviews.process_one, kos_api_client, slack_conn, cfg)
        except asyncio.CancelledError:
            logger.info("Poller cancelled.")
            break
        except Exception:
            logger.exception("Error processing outbox item")

        await asyncio.sleep(cfg.poll_interval_seconds)
