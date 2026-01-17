import logging
import sys

import uvicorn

import config
import db
import kos_api
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
    cfg = config.load_config()
    logger.info("Creating kOS API client...")
    kos_api_client = kos_api.KosApiClient(
        base_url=cfg.kos_api_base_url,
        token=cfg.kos_api_token,
        timeout_seconds=cfg.kos_api_timeout_seconds,
    )
    logger.info("kOS API client created successfully.")

    logger.info("Creating slack database engine...")
    slack_engine = db.create_slack_db_engine(cfg.sqlite_db_path)
    logger.info("Slack database engine created successfully: %s", slack_engine)

    logger.info("Creating gmail service...")
    gmail_service = get_gmail_service(credentials_file=cfg.credentials_file, token_file=cfg.token_file)
    logger.info("Gmail service created: %s", gmail_service)

    logger.info("Creating services container...")
    services = Services(
        config=cfg,
        kos_api_client=kos_api_client,
        slack_db_engine=slack_engine,
        gmail_service=gmail_service
    )

    logger.info("Creating FastAPI app...")
    app = make_app(services)
    
    port = cfg.port
    
    logger.info("Starting Uvicorn on port %s", port)
    uvicorn.run(app, host="0.0.0.0", port=port)
