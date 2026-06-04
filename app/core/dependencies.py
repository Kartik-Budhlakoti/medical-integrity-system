from fastapi.security import OAuth2PasswordBearer
from fastapi import Depends 
from app.core.jwt import verify_token
from app.schemas.token import TokenData

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

def get_current_user(token:str = Depends(oauth2_scheme)) -> TokenData:
    return verify_token(token)
