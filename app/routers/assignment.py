from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from app.database import get_db
from app.schemas.assignment import AssignmentCreate, AssignmentResponse
from app.core.dependencies import get_current_user
from app.schemas.token import TokenData
from app.core.audit import log_action
from app.models.patient import Patient
from app.models.user import User
from app.models.patient_assignment import PatientAssignment

router = APIRouter(prefix="/assignments", tags=["assignments"])

@router.post("/assign", response_model=AssignmentResponse)
def assign(request: Request, assignment_data: AssignmentCreate, db: Session = Depends(get_db), current: TokenData = Depends(get_current_user)):
    if current.role != "Admin":
        log_action(db=db, user_id=current.user_id, action="PATIENT_ASSIGNMENT_FAILED",
                   entity_type="patient_assignments", entity_id=0,
                   result="FAILURE", ip_address=request.client.host)
        raise HTTPException(status_code=403, detail="Not authorized")

    patient = db.query(Patient).filter(Patient.id == assignment_data.patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    user = db.query(User).filter(User.id == assignment_data.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if user.role.role_name not in ["Doctor", "Nurse"]:
        raise HTTPException(status_code=400, detail="Can only assign Doctors or Nurses")

    existing = db.query(PatientAssignment).filter(
        PatientAssignment.patient_id == assignment_data.patient_id,
        PatientAssignment.user_id == assignment_data.user_id,
        PatientAssignment.is_active.is_(True)
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="User already assigned to this patient")

    new_assignment = PatientAssignment(
        patient_id=assignment_data.patient_id,
        user_id=assignment_data.user_id,
        assigned_by_id=current.user_id,
        is_active=True
    )
    db.add(new_assignment)
    db.commit()
    db.refresh(new_assignment)
    log_action(db=db, user_id=current.user_id, action="PATIENT_ASSIGNED",
               entity_type="patient_assignments", entity_id=new_assignment.id,
               result="SUCCESS", ip_address=request.client.host)
    return new_assignment