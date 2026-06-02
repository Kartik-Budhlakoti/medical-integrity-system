from jose import JWTError , jwt
from datetime import datetime , timezone , timedelta
from dotenv import load_dotenv
import os
from app.schemas.token import TokenData
from fastapi import HTTPException
load_dotenv()
SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = os.getenv("ALGORITHM")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES"))

def create_access_token(user_id: int , role:str) -> str:
    payload = {
        "user_id": user_id,
        "role": role,
        "exp":datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    }
    token_string = jwt.encode(payload , SECRET_KEY, ALGORITHM)
    return token_string

def verify_token(token:str):
    try:
        payload= jwt.decode(token , SECRET_KEY , algorithms=[ALGORITHM])
        user_id = payload["user_id"]
        role = payload["role"]
        return TokenData(user_id=user_id , role=role)
    except JWTError:
        raise HTTPException(status_code=401 , detail="Token verification failed")
