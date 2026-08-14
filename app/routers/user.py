from fastapi import APIRouter, Depends , HTTPException , Request
from app.schemas import user
from app.schemas.token import TokenData 
from app.database import get_db
from sqlalchemy.orm import Session 
from app.core.security import hash_password
from app.models.user import User , Role
from app.core.dependencies import get_current_user
from app.core.audit import log_action

router = APIRouter(prefix="/users", tags=["users"])

@router.post("/create" , response_model=user.UserResponse)
def create_user(request : Request,user_data : user.UserCreate , db: Session = Depends(get_db), current: TokenData = Depends(get_current_user)):
    if current.role not in ["SuperAdmin" , "Admin"]:
        log_action(
                    db=db,
                    user_id= current.user_id,
                    action= "USER_CREATION_FAILED",
                    entity_type = "users",
                    entity_id =0, 
                    result= "FAILURE",
                    ip_address=request.client.host
                )
        raise HTTPException(status_code=403 , detail="Not authorized")

    role = db.query(Role).filter(Role.id == user_data.role_id).first()
    if not role: 
        raise HTTPException(status_code=400 , detail="Invalid role")

    if current.role == "Admin" and role.role_name not in ["Doctor", "Nurse"]:
        log_action(db=db, user_id=current.user_id, action="PRIVILEGE_ESCALATION_ATTEMPT",
               entity_type="roles", entity_id=role.id,
               result="FAILURE", ip_address=request.client.host)
        raise HTTPException(status_code=403 , detail="Admin can only create Doctor or Nurse accounts")

    if role.role_name == "SuperAdmin":
        log_action(db=db, user_id=current.user_id, action="PRIVILEGE_ESCALATION_ATTEMPT",
               entity_type="roles", entity_id=role.id,
               result="FAILURE", ip_address=request.client.host)
        raise HTTPException(status_code=403 , detail="SuperAdmin accounts can only be created via bootstrap")

    existing = db.query(User).filter(User.email == user_data.email).first()
    if existing:
        log_action(
            db=db,
            user_id= current.user_id,
            action= "USER_CREATION_FAILED",
            entity_type = "users",
            entity_id =existing.id, 
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
            entity_id =new_user.id, 
            result= "SUCCESS",
            ip_address=request.client.host
        )
    return new_user