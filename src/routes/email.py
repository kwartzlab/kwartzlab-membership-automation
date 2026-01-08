from fastapi import APIRouter, HTTPException, Request

import db
import mailer

router = APIRouter()

@router.post("/email/{user_id}/return_visit")
def send_return_visit_email(user_id: int, request: Request):
    engine = request.app.state.engine
    gmail_service = request.app.state.gmail_service
    
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
def send_acceptance_email(user_id: int, request: Request):
    engine = request.app.state.engine
    gmail_service = request.app.state.gmail_service

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