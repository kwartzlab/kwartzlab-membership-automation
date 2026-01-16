from dataclasses import dataclass
from config import Config
import db

@dataclass
class Services:
    config: Config
    kos_db_engine: db.Engine
    slack_db_engine: db.Engine
    gmail_service: any