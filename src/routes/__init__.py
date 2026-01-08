import asyncio
import logging
import db

from fastapi import FastAPI
from config import Config
from contextlib import asynccontextmanager, suppress

from routes.health import router as health_router
from routes.outbox import router as outbox_router
from routes.email import router as email_router

from slack_app import build_slack_runtime
from worker import poller_loop

logger = logging.getLogger(__name__)

def make_app(cfg: Config, engine: db.Engine, gmail_service):

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info("Starting application lifespan...")

        tasks: list[asyncio.Task] = []
        
        tasks.append(asyncio.create_task(poller_loop(cfg=cfg, engine=engine)))

        slack_runtime = build_slack_runtime(cfg=cfg, engine=engine)
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

            await asyncio.to_thread(engine.dispose)

            logger.info("Lifespan stopped.")

    app = FastAPI(lifespan=lifespan)

    app.state.engine = engine
    app.state.cfg = cfg
    app.state.gmail_service = gmail_service
    

    app.include_router(health_router)
    app.include_router(outbox_router)
    app.include_router(email_router)
    
    return app