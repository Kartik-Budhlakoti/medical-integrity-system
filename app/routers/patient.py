from fastapi import APIRouter , Depends , HTTPException , Request
from sqlalchemy.orm import Session
from app.database import get_db
from app.schemas.patient import PatientCreate , PatientResponse
from app.models.patient import Patient
from app.core.audit import log_action
from app.core.dependencies import get_current_user
from app.schemas.token import TokenData

router = APIRouter(prefix="/patients" , tags=["patients"])

@router.post("/create" , response_model=PatientResponse)
def patient_creation(request:Request , patient_data : PatientCreate , db : Session = Depends(get_db) , current : TokenData = Depends(get_current_user)):
    if current.role not in ["Admin" , "Doctor" , "Nurse"]:
        log_action(
            db=db,
            user_id= current.user_id,
            action= "PATIENT_CREATION_FAILED",
            entity_type = "patients",
            entity_id =0, 
            result= "FAILURE",
            ip_address=request.client.host
        )
        raise HTTPException(status_code = 403 , detail="Not authorized")
    new_patient = Patient(
        full_name = patient_data.full_name,
        dob = patient_data.dob,
        height = patient_data.height,
        weight = patient_data.weight,
        chief_complaint = patient_data.chief_complaint,
        is_emergency = patient_data.is_emergency
        )
    db.add(new_patient)
    db.commit()
    db.refresh(new_patient)
    log_action(
            db=db,
            user_id= current.user_id,
            action= "PATIENT_CREATION_SUCCESSFUL",
            entity_type = "patients",
            entity_id =new_patient.id, 
            result= "SUCCESS",
            ip_address=request.client.host
        )
    return new_patient

@router.get("/{patient_id}", response_model=PatientResponse)
def get_patient(request: Request, patient_id: int, db: Session = Depends(get_db), current: TokenData = Depends(get_current_user)):
    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")    
    if current.role == "Admin":
        log_action(db=db, user_id=current.user_id, action="PATIENT_ACCESSED",
                   entity_type="patients", entity_id=patient.id,
                   result="SUCCESS", ip_address=request.client.host)
        return patient
    
    from app.models.patient_assignment import PatientAssignment
    assignment = db.query(PatientAssignment).filter(
        PatientAssignment.patient_id == patient_id,
        PatientAssignment.user_id == current.user_id,
        PatientAssignment.is_active == True
    ).first()
    
    if not assignment:
        log_action(db=db, user_id=current.user_id, action="PATIENT_ACCESS_DENIED",
                   entity_type="patients", entity_id=patient_id,
                   result="FAILURE", ip_address=request.client.host)
        raise HTTPException(status_code=403, detail="Not assigned to this patient")
    
    log_action(db=db, user_id=current.user_id, action="PATIENT_ACCESSED",
               entity_type="patients", entity_id=patient.id,
               result="SUCCESS", ip_address=request.client.host)
    return patient
    
