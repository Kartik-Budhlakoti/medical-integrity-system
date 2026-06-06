from fastapi import APIRouter , Depends , HTTPException
from sqlalchemy.orm import Session
from app.models.user import Role , User
from app.database import get_db
from app.schemas import bootstrap
from app.core.security import hash_password

router = APIRouter(prefix="/bootstrap" , tags=["bootstrap"])

@router.post('/superadmin')
def create_super_admin(data: bootstrap.BootstrapCreate ,db :Session = Depends(get_db)):

    existing_superadmin = db.query(User).join(Role).filter(Role.role_name == "SuperAdmin").first()
    if existing_superadmin:
        raise HTTPException(status_code=403 , detail="System already initialized")
    
    roles_existing = db.query(Role).first()
    if not roles_existing:
        roles = [
            Role(role_name="SuperAdmin", dept_name="Administration"),
            Role(role_name="Admin", dept_name="Administration"),
            Role(role_name="Doctor", dept_name="Medical"),
            Role(role_name="Nurse", dept_name="Medical")
        ]
        for role in roles:
            db.add(role)
        db.commit()

    superadmin_role = db.query(Role).filter(Role.role_name == "SuperAdmin").first()

    if not superadmin_role:
        raise HTTPException(status_code=500 , detail="SuperAdmin role not found")

    superadmin = User(
        full_name = data.full_name , 
        email = data.email,
        pass_hash = hash_password(data.password),
        role_id = superadmin_role.id
    )
    db.add(superadmin)
    db.commit()
    db.refresh(superadmin)
    return {"message" : "System initialized successfully"}