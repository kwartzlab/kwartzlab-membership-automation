from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from services import Services, get_services

bearer_scheme = HTTPBearer(auto_error=False)


def verify_api_token(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    services: Annotated[Services, Depends(get_services)],
) -> None:
    token = credentials.credentials if credentials else None
    if not token or token != services.config.api_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"message": "Unauthorized"},
            headers={"WWW-Authenticate": "Bearer"},
        )
