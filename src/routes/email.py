from fastapi import APIRouter, HTTPException, Request, Depends

import db
import mailer
from services import Services

router = APIRouter()

def get_services(request: Request) -> Services:
    return request.app.state.services

@router.post("/email/{user_id}/return_visit")
def send_return_visit_email(user_id: int, request: Request, services: Services = Depends(get_services)):
    engine = services.kos_db_engine
    gmail_service = services.gmail_service
    
    with engine.begin() as conn:
        user = db.get_user_by_id(conn=conn, user_id=user_id)
    
    if user is None:
        raise HTTPException(status_code=404, detail={"message": "Could not find user"})
            
    message = mailer.build_return_visit_email(user)
    mailer.send_message(
        service=gmail_service,
        user_id=mailer.SENDER_USER_ID,
        message=message
    )
    return user

@router.post("/email/{user_id}/acceptance/", status_code=204)
def send_acceptance_email(user_id: int, request: Request, services: Services = Depends(get_services)):
    engine = services.kos_db_engine
    gmail_service = services.gmail_service

    with engine.begin() as conn:
        user = db.get_user_by_id(conn=conn, user_id=user_id)
    
    if user is None:
        raise HTTPException(status_code=404, detail={"message": "Could not find user"})
    
    message = mailer.build_acceptance_email(user)
    
    mailer.send_message(
        service=gmail_service,
        user_id=mailer.SENDER_USER_ID,
        message=message
    )
    return user

@router.post("/email/{user_id}/rejection")
def send_rejection_email(user_id: int):
    return "Not implemented"