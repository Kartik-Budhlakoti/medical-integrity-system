from fastapi import APIRouter, Depends , HTTPException , Request
from app.schemas import user
from app.schemas.token import TokenData 
from app.database import get_db
from sqlalchemy.orm import Session 
from app.core.security import hash_password
from app.models.user import User
from app.core.dependencies import get_current_user
from app.core.audit import log_action

router = APIRouter(prefix="/users", tags=["users"])

@router.post("/create" , response_model=user.UserResponse)
def create_user(request : Request,user_data : user.UserCreate , db: Session = Depends(get_db), current: TokenData = Depends(get_current_user)):
    if current.role not in ["SuperAdmin" , "Admin"]:
        raise HTTPException(status_code=403 , detail="Not authorized")
    existing = db.query(User).filter(User.email == user_data.email).first()
    if existing:
        log_action(
            db=db,
            user_id= current.user_id,
            action= "USER_CREATION_FAILED",
            entity_type = "users",
            entity_id =current.user_id, 
            result= "FAILURE",
            ip_address=request.client.host
        )
        raise HTTPException(status_code=400 , detail="Email already registered")

    new_user = User(
        full_name = user_data.full_name,
        email = user_data.email ,
        pass_hash = hash_password(user_data.password),
        role_id = user_data.role_id
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    log_action(
            db=db,
            user_id= current.user_id,
            action= "USER_CREATION_SUCCESSFUL",
            entity_type = "users",
            entity_id =current.user_id, 
            result= "SUCCESS",
            ip_address=request.client.host
        )
    return new_user