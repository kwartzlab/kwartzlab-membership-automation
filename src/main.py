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
    logger.info("Creating kos database engine...")
    cfg = config.load_config()
    kos_engine = db.create_kos_db_engine(db_host=cfg.db_host, db_port=cfg.db_port,
                                         db_name=cfg.db_name, db_user=cfg.db_user,
                                         db_password=cfg.db_password)
    logger.info("Kos database engine created successfully: %s", kos_engine)

    logger.info("Creating slack database engine...")
    slack_engine = db.create_slack_db_engine(db_url=f"sqlite:///{cfg.sqlite_db_path}")
    logger.info("Slack database engine created successfully: %s", slack_engine)

    logger.info("Creating gmail service...")
    gmail_service = get_gmail_service(credentials_file=config.Path(cfg.credentials_file), token_file=config.Path(cfg.token_file))
    logger.info("Gmail service created: %s", gmail_service)

    logger.info("Creating services container...")
    services = Services(
        config=cfg,
        kos_db_engine=kos_engine,
        slack_db_engine=slack_engine,
        gmail_service=gmail_service
    )

    logger.info("Creating FastAPI app...")
    app = make_app(services)
    
    port = cfg.port
    
    logger.info("Starting Uvicorn on port %s", port)
    uvicorn.run(app, host="0.0.0.0", port=port)
