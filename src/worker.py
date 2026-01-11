import asyncio
import logging

import db

logger = logging.getLogger(__name__)

async def poller_loop(cfg, engine, slack_engine):
    while True:
        try:
            logger.info("Checking for missed messages...")
            await asyncio.to_thread(db.process_one, engine, slack_engine, cfg) 
        except asyncio.CancelledError:
            logger.info("Poller cancelled.")
            break
        except Exception:
            logger.exception("Error processing outbox item")

        await asyncio.sleep(cfg.poll_interval_seconds)