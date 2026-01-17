from dataclasses import dataclass
from config import Config
import db
import kos_api

@dataclass
class Services:
    config: Config
    kos_api_client: kos_api.KosApiClient
    slack_db_engine: db.Engine
    gmail_service: any
