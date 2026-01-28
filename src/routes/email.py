from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

import services.mailer as mailer
from services import Services, get_services

router = APIRouter()


@router.post("/email/{user_id}/return_visit")
def send_return_visit_email(
    user_id: int,
    services: Annotated[Services, Depends(get_services)],
):
    kos_api_client = services.kos_api_client
    gmail_service = services.gmail_service

    user = kos_api_client.get_user(user_id)

    if user is None:
        raise HTTPException(status_code=404, detail={"message": "Could not find user"})

    message = mailer.build_return_visit_email(user)
    mailer.send_message(service=gmail_service, user_id=mailer.SENDER_USER_ID, message=message)
    return user


@router.post("/email/{user_id}/acceptance", status_code=204)
def send_acceptance_email(
    user_id: int,
    services: Annotated[Services, Depends(get_services)],
):
    kos_api_client = services.kos_api_client
    gmail_service = services.gmail_service

    user = kos_api_client.get_user(user_id)

    if user is None:
        raise HTTPException(status_code=404, detail={"message": "Could not find user"})

    message = mailer.build_acceptance_email(user)

    mailer.send_message(service=gmail_service, user_id=mailer.SENDER_USER_ID, message=message)


@router.post("/email/{user_id}/rejection", status_code=204)
def send_rejection_email(
    user_id: int,
    services: Annotated[Services, Depends(get_services)],
):
    kos_api_client = services.kos_api_client
    gmail_service = services.gmail_service

    user = kos_api_client.get_user(user_id)

    if user is None:
        raise HTTPException(status_code=404, detail={"message": "Could not find user"})

    message = mailer.build_rejection_email(user)

    mailer.send_message(service=gmail_service, user_id=mailer.SENDER_USER_ID, message=message)