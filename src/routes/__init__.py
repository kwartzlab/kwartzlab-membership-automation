import asyncio
import logging
import db

from fastapi import FastAPI
from contextlib import asynccontextmanager, suppress

from routes.health import router as health_router
from routes.outbox import router as outbox_router
from routes.email import router as email_router

from slack_app import build_slack_runtime
from worker import poller_loop
from services import Services

logger = logging.getLogger(__name__)

def make_app(services: Services):

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info("Starting application lifespan...")

        tasks: list[asyncio.Task] = []
        with services.slack_db_engine.begin() as conn:
            await asyncio.to_thread(db.create_slack_tables, conn)
        
        tasks.append(asyncio.create_task(poller_loop(cfg=services.config, kos_api_client=services.kos_api_client, slack_engine=services.slack_db_engine)))

        slack_runtime = build_slack_runtime(cfg=services.config, kos_api_client=services.kos_api_client, slack_db_engine=services.slack_db_engine, mailer=services.gmail_service)
        tasks.extend(slack_runtime.start_tasks())

        try:
            yield
        finally:
            logger.info("Stopping lifespan...")

            for t in tasks:
                t.cancel()
            for t in tasks:
                with suppress(asyncio.CancelledError):
                    await t

            await asyncio.to_thread(services.slack_db_engine.dispose)

            logger.info("Lifespan stopped.")

    app = FastAPI(lifespan=lifespan)

    app.state.services = services
    

    app.include_router(health_router)
    app.include_router(outbox_router)
    app.include_router(email_router)
    
    return app
