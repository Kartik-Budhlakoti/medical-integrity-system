from fastapi import APIRouter , Depends , HTTPException , Request
from sqlalchemy.orm import Session
from app.database import get_db
from app.schemas.patient import PatientCreate , PatientResponse , PatientUpdate
from app.models.patient import Patient
from app.core.audit import log_action
from app.core.dependencies import get_current_user
from app.schemas.token import TokenData
from app.models.patient_assignment import PatientAssignment


router = APIRouter(prefix="/patients" , tags=["patients"])

ROLE_UPDATE_PERMISSIONS = {
    "Admin": {"is_admitted","is_emergency","chief_complaint"},
    "Doctor": {"is_emergency","chief_complainr"},
    "Nurse" : {"height","weight"}
}

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

@router.get("/", response_model=list[PatientResponse])
def get_all_patients(request: Request , db: Session = Depends(get_db), current : TokenData = Depends(get_current_user)):
    if current.role not in ["Admin", "Doctor", "Nurse"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    if current.role == "Admin":
        patients = db.query(Patient).all()
        log_action(db=db, user_id=current.user_id, action="PATIENTS_ACCESSED",
                   entity_type="patients", entity_id=0,
                   result="SUCCESS", ip_address=request.client.host)
        return patients
    
    if current.role in ["Doctor", "Nurse"]:
        assigned = db.query(PatientAssignment).filter(
            PatientAssignment.user_id == current.user_id,
            PatientAssignment.is_active.is_(True)
        ).all()
        if not assigned:
            log_action(db=db, user_id=current.user_id, action="PATIENTS_ACCESS_DENIED",
                    entity_type="patients", entity_id=0,
                    result="FAILURE", ip_address=request.client.host)
            raise HTTPException(status_code=403, detail="Not assigned to this patient")
        
        patient_ids = [a.patient_id for a in assigned]
        patients = db.query(Patient).filter(Patient.id.in_(patient_ids)).all()
        log_action(db=db, user_id=current.user_id, action="PATIENTS_ACCESSED",
                entity_type="patients", entity_id=0,
                result="SUCCESS", ip_address=request.client.host)
        return patients 
    
    raise HTTPException(status_code=403, detail="Not authorized")

@router.get("/{patient_id}", response_model=PatientResponse)
def get_patient(request: Request, patient_id: int, db: Session = Depends(get_db), current: TokenData = Depends(get_current_user)):
    if current.role not in ["Admin", "Doctor", "Nurse"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")    
    if current.role == "Admin":
        log_action(db=db, user_id=current.user_id, action="PATIENT_ACCESSED",
                   entity_type="patients", entity_id=patient.id,
                   result="SUCCESS", ip_address=request.client.host)
        return patient
    
    assignment = db.query(PatientAssignment).filter(
        PatientAssignment.patient_id == patient_id,
        PatientAssignment.user_id == current.user_id,
        PatientAssignment.is_active.is_(True)
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

@router.patch("/{patient_id}" , response_model = PatientResponse)
def update_patient(request: Request , patient_id:int , patient_data : PatientUpdate, db:Session = Depends(get_db), current : TokenData = Depends(get_current_user)):
    if current.role not in ROLE_UPDATE_PERMISSIONS:
        log_action(db=db, user_id=current.user_id, action="PATIENT_UPDATE_FAILED",
                   entity_type="patients", entity_id=patient_id,
                   result="FAILURE", ip_address=request.client.host)
        raise HTTPException(status_code=403, detail="Not authorized")
    
    requested_fields = patient_data.model_fields_set
    allowed_fields = ROLE_UPDATE_PERMISSIONS[current.role]

    if not requested_fields.issubset(allowed_fields):
        blocked = requested_fields - allowed_fields
        log_action(db=db, user_id=current.user_id, action="PATIENT_UPDATE_FAILED",
                   entity_type="patients", entity_id=patient_id,
                   result="FAILURE", ip_address=request.client.host)
        raise HTTPException(status_code=403, detail=f"Not authorized to update: {blocked}")
    
    patient = db.query(Patient).filter(Patient.id == patient_id).first()

    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    if current.role in ["Doctor", "Nurse"]:
        assignment = db.query(PatientAssignment).filter(
            PatientAssignment.patient_id == patient_id,
            PatientAssignment.user_id == current.user_id,
            PatientAssignment.is_active.is_(True)
        ).first()
        if not assignment:
            log_action(db=db, user_id=current.user_id, action="PATIENT_UPDATE_FAILED",
                   entity_type="patients", entity_id=patient_id,
                   result="FAILURE", ip_address=request.client.host)
        raise HTTPException(status_code=403, detail=f"Not assigned to this patient")
    
    update_data = patient_data.model_dump(exclude_unset=True)
    for field , value in update_data.items():
        setattr(patient , field , value)
    
    db.commit()
    db.refresh(patient)
    log_action(db=db, user_id=current.user_id, action="PATIENT_UPDATED",
                   entity_type="patients", entity_id=patient_id,
                   result="SUCCESS", ip_address=request.client.host)
    return patient


    
