from dataclasses import dataclass
from typing import Any

from fastapi import Request
from sqlalchemy.engine import Engine

import services.kos_api as kos_api
from config import Config


@dataclass
class Services:
    config: Config
    kos_api_client: kos_api.KosApiClient
    slack_db_engine: Engine
    gmail_service: Any


def get_services(request: Request) -> Services:
    return request.app.state.services
