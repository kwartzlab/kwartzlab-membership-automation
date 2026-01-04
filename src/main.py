import asyncio
import logging
import sys

from contextlib import asynccontextmanager
from fastapi import FastAPI
import uvicorn

import config
import db
from mailer import get_gmail_service


# ---------------- logging setup ----------------
logging.basicConfig(
    level=logging.INFO,
    stream=sys.stdout,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------- app factory ----------------
def make_app(cfg: config.Config, engine: db.Engine):

    async def background_loop():
        while True:
            try:
                logger.info("Checking for missed messages...")
                db.process_one(engine)
            except asyncio.CancelledError:
                logger.info("Background worker cancelled.")
                break
            except Exception:
                logger.exception("Error processing outbox item")
            await asyncio.sleep(cfg.poll_interval_seconds)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info("Starting application lifespan...")
        app.state.engine = engine
        worker = asyncio.create_task(background_loop())
        app.state.worker = worker
        try:
            yield
        finally:
            logger.info("Shutting down application lifespan...")
            worker.cancel()
            try:
                await worker
            except asyncio.CancelledError:
                pass
            engine.dispose()
            logger.info("Lifespan shutdown complete.")

    app = FastAPI(lifespan=lifespan)

    @app.get("/health")
    async def get_health():
        return {"ok": True}

    @app.post("/process-one/{outbox_id}")
    def process_one_api(outbox_id: int):
        submit_successful = db.process_one(engine, outbox_id)
        return {"submission_successful": submit_successful}

    @app.post("/email/{user_id}/return_visit")
    def send_return_visit_email(user_id: int):
        return "Not implemented"
    
    @app.post("/email/{user_id}/acceptance/")
    def send_acceptance_email(user_id: int):
        user = db.get_user_by_id(engine=engine, user_id=user_id)
        return user

    @app.post("/email/{user_id}/rejection")
    def send_rejection_email(user_id: int):
        return "Not implemented"
    
    
    return app


# ---------------- entrypoint ----------------
if __name__ == "__main__":
    logger.info("Creating database engine...")
    cfg = config.load_config()
    engine = db.create_db_engine(cfg)
    logger.info("Database engine created successfully: %s", engine)

    logger.info("Creating gmail service...")
    gmail_service = get_gmail_service()
    logger.info("Gmail service created: %s", gmail_service)

    logger.info("Creating FastAPI app...")
    app = make_app(cfg, engine)
    
    port = cfg.port
    
    logger.info("Starting Uvicorn on port %s", port)
    uvicorn.run(app, host="0.0.0.0", port=port)
