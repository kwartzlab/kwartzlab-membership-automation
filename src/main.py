import logging
import sys

import uvicorn

import config
import db
from mailer import get_gmail_service
from routes import make_app

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

    logger.info("Creating gmail service...")
    gmail_service = get_gmail_service()
    logger.info("Gmail service created: %s", gmail_service)

    logger.info("Creating FastAPI app...")
    app = make_app(cfg, engine, gmail_service)
    
    port = cfg.port
    
    logger.info("Starting Uvicorn on port %s", port)
    uvicorn.run(app, host="0.0.0.0", port=port)
