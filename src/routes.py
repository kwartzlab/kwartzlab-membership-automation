import asyncio
import logging
import db

from fastapi import FastAPI, HTTPException
from config import Config
from contextlib import asynccontextmanager

import mailer
import email_templates
import slack

logger = logging.getLogger(__name__)

def make_app(cfg: Config, engine: db.Engine, gmail_service):
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
            logger.info("Waiting %s seconds before checking again", cfg.poll_interval_seconds)
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

    @app.post("/process-form-outbox/{outbox_id}")
    def process_outbox(outbox_id: int):
        with engine.begin() as conn:
            application = db.get_application_from_outbox(conn=conn, outbox_id=outbox_id)
            try:
                logging.log("Processing submission %s", {application['form_submission_id']})
                slack.post_application(
                        cfg=cfg.load_config(),
                        applicantion_data=application["data"],
                    )
            except Exception as exc:
                logging.log("Failed to process outbox_id: %s", outbox_id)
                db.mark_outbox_failed(conn=conn, outbox_id=outbox_id, exc=exc)                
                return {"Submission Failed %s", exc}

            db.mark_outbox_success(conn=conn, outbox_id=outbox_id)
            return {"Submission Successful"}

    @app.post("/email/{user_id}/return_visit")
    def send_return_visit_email(user_id: int):
        with engine.begin() as conn:
            user = db.get_user_by_id(conn=conn, user_id=user_id)
        
        if user is None:
            raise HTTPException(status_code=404, detail={"message": "Could not find user"})
                
        message = mailer.build_return_visit_email(user)
        mailer.send_message(
            service=gmail_service,
            user_id=mailer.SENDER_USER_ID,
            message=message
        )
        return user
    
    @app.post("/email/{user_id}/acceptance/", status_code=204)
    def send_acceptance_email(user_id: int):
        with engine.begin() as conn:
            user = db.get_user_by_id(conn=conn, user_id=user_id)
        
        if user is None:
            raise HTTPException(status_code=404, detail={"message": "Could not find user"})
        
        message = mailer.build_acceptance_email(user)
        
        # mailer.send_message(
        #     service=gmail_service,
        #     user_id=mailer.SENDER_USER_ID,
        #     message=message
        # )
        return user

    @app.post("/email/{user_id}/rejection")
    def send_rejection_email(user_id: int):
        return "Not implemented"
    
    return app