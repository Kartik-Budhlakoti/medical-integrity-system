from fastapi import APIRouter , Depends,HTTPException , Request
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.user import User
from app.schemas.user import UserLogin
from app.schemas.token import Token , TokenData
from app.core.security import verify_password , hash_password
from app.core.jwt import create_access_token
from app.core.audit import log_action
from slowapi import Limiter

from slowapi.util import get_remote_address
from app.core.dependencies import get_current_user
from app.schemas.user import ChangePasswordRequest , ChangePasswordResponse

limiter = Limiter(key_func=get_remote_address)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=Token)
@limiter.limit("5/minute")
def login(request : Request ,credentials:UserLogin , db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == credentials.email).first()

    if not user:
        log_action(
            db=db,
            user_id= None,
            action= "LOGIN_FAILED",
            entity_type = "users",
            entity_id = 0,
            result= "FAILURE",
            ip_address=request.client.host
        )
        raise HTTPException(status_code=401 , detail="Invalid credentials")
    if len(credentials.password.encode('utf-8')) > 72:
        log_action(
            db=db,
            user_id=user.id,
            action = "LOGIN_FAILED",
            entity_type="users",
            entity_id=user.id,
            result="FAILURE",
            ip_address=request.client.host
        )
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not verify_password(credentials.password, user.pass_hash):
        log_action(
            db=db,
            user_id= user.id,
            action= "LOGIN_FAILED",
            entity_type = "users",
            entity_id = user.id,
            result= "FAILURE",
            ip_address=request.client.host
        )
        raise HTTPException(status_code=401 , detail="Invalid credentials")
    token = create_access_token(user_id=user.id , role=user.role.role_name)
    log_action(
            db=db,
            user_id= user.id,
            action= "LOGIN_SUCCESS",
            entity_type = "users",
            entity_id =user.id, 
            result= "SUCCESS",
            ip_address=request.client.host
        )
    return Token(access_token=token , token_type="bearer")

@router.post("/change-password", response_model=ChangePasswordResponse)
@limiter.limit("5/minute")
def change_password(request: Request , password_data: ChangePasswordRequest,
                    db : Session = Depends(get_db) , current: TokenData = Depends(get_current_user)):
    user = db.query(User).filter(User.id == current.user_id).first()
    if not user:
        log_action(
            db=db,
            user_id= current.user_id,
            action= "PASSWORD_CHANGE_FAILED",
            entity_type = "users",
            entity_id = current.user_id,
            result= "FAILURE",
            ip_address=request.client.host
        )
        raise HTTPException(status_code=404 , detail="Invalid credentials")
    
    if len(password_data.old_password.encode('utf-8')) > 72:
        log_action(
            db=db,
            user_id= current.user_id,
            action= "PASSWORD_CHANGE_FAILED",
            entity_type = "users",
            entity_id = current.user_id,
            result= "FAILURE",
            ip_address=request.client.host
        )
        raise HTTPException(status_code=401 , detail="Invalid credentials")

    if not verify_password(password_data.old_password , user.pass_hash):
        log_action(
            db=db,
            user_id= current.user_id,
            action= "PASSWORD_CHANGE_FAILED",
            entity_type = "users",
            entity_id = current.user_id,
            result= "FAILURE",
            ip_address=request.client.host
        )
        raise HTTPException(status_code=401 , detail="Invalid credentials")
    
    user.pass_hash = hash_password(password_data.new_password)
    db.commit()
    log_action(
            db=db,
            user_id= current.user_id,
            action= "PASSWORD_CHANGE_SUCCESSFUL",
            entity_type = "users",
            entity_id = current.user_id,
            result= "SUCCESS",
            ip_address=request.client.host
        )
    return ChangePasswordResponse(message="Password changed successfully")