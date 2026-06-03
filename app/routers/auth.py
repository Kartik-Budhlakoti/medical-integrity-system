from fastapi import APIRouter , Depends,HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.user import User
from app.schemas.user import UserLogin
from app.schemas.token import Token 
from app.core.security import verify_password 
from app.core.jwt import create_access_token
router = APIRouter(prefix="/auth", tags=["auth"])

@router.post("/login", response_model=Token)
def login(credentials:UserLogin , db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == credentials.email).first()

    if not user:
        raise HTTPException(status_code=401 , detail="Invalid credentials")

    if not verify_password(credentials.password, user.pass_hash):
        raise HTTPException(status_code=401 , detail="Invalid credentials")

    token = create_access_token(user_id=user.id , role=user.role.role_name)
    return Token(access_token=token , token_type="bearer")