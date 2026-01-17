from dataclasses import dataclass

import db
import kos_api
from config import Config


@dataclass
class Services:
    config: Config
    kos_api_client: kos_api.KosApiClient
    slack_db_engine: db.Engine
    gmail_service: any
