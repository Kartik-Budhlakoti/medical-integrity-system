from fastapi import APIRouter , Depends,HTTPException , Request
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.user import User
from app.schemas.user import UserLogin
from app.schemas.token import Token 
from app.core.security import verify_password 
from app.core.jwt import create_access_token
from app.core.audit import log_action

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=Token)
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
