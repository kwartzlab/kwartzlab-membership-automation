import logging
import sys

import uvicorn

import config
import db
from mailer import get_gmail_service
from routes import make_app
from services import Services

logging.basicConfig(
    level=logging.INFO,
    stream=sys.stdout,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


if __name__ == "__main__":
    logger.info("Creating database engine...")
    cfg = config.load_config()
    engine = db.create_db_engine(cfg)
    logger.info("Database engine created successfully: %s", engine)

    logger.info("Creating slack database engine...")
    slack_engine = db.create_slack_db_engine()
    logger.info("Slack database engine created successfully: %s", slack_engine)

    logger.info("Creating gmail service...")
    gmail_service = get_gmail_service()
    logger.info("Gmail service created: %s", gmail_service)

    logger.info("Creating services container...")
    services = Services(
        config=cfg,
        kos_db_engine=engine,
        slack_db_engine=slack_engine,
        gmail_service=gmail_service
    )

    logger.info("Creating FastAPI app...")
    app = make_app(services)
    
    port = cfg.port
    
    logger.info("Starting Uvicorn on port %s", port)
    uvicorn.run(app, host="0.0.0.0", port=port)
