from fastapi.security import OAuth2PasswordBearer 
from fastapi import Depends , HTTPException , Request
from sqlalchemy.orm import Session
from app.core.jwt import verify_token
from app.schemas.token import TokenData
from app.database import get_db
from app.core.audit import log_action
from app.models.user import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

def get_current_user(request: Request, token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> TokenData:
    try:
        token_data = verify_token(token)
    except HTTPException:
        log_action(
            db=db,
            user_id=None,
            action="TOKEN_VERIFICATION_FAILED",
            entity_type="users", entity_id=0,
            result="FAILURE",
            ip_address=request.client.host,
        )
        raise HTTPException(status_code=401, detail="Invalid credentials")
    user = db.query(User).filter(User.id == token_data.user_id).first()
    if not user or  not user.is_active:
        log_action (
            db=db,
            user_id=token_data.user_id,
            action="DEACTIVATED_ACCOUNT_ACCESS_ATTEMPT",
            entity_type="users", entity_id=token_data.user_id,
            result="FAILURE",
            ip_address=request.client.host,
        )
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return token_data
