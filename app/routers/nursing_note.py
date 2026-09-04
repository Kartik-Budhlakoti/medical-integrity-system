from fastapi import APIRouter, Request, Depends, HTTPException
from sqlalchemy.orm import Session
from app.models.nursing_note import NursingNote
from app.schemas.nursing_note import NursingNoteCreate , NursingNoteResponse
from app.core.dependencies import get_current_user
from app.schemas.token import TokenData
from app.database import get_db
from app.models.patient import Patient
from app.models.patient_assignment import PatientAssignment
from app.core.audit import log_action
from typing import List

router = APIRouter(prefix="/nursing-notes", tags=["nursing-notes"])

@router.post("/create", response_model=NursingNoteResponse)
def create_nursing_note(
    request: Request,
    note_data: NursingNoteCreate,
    db:Session= Depends(get_db), current:TokenData= Depends(get_current_user)):

    if current.role != "Nurse":
        log_action(db=db, user_id=current.user_id, action="NOTE_CREATION_FAILED",
                           entity_type="nursing_notes", entity_id=note_data.patient_id,
                           result="FAILURE", ip_address=request.client.host)
        raise HTTPException(status_code=403 , detail="Only nurse can create nursing note")

    patient = db.query(Patient).filter(Patient.id == note_data.patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    assignment= db.query(PatientAssignment).filter(
        PatientAssignment.patient_id == note_data.patient_id,
        PatientAssignment.user_id == current.user_id,
        PatientAssignment.is_active.is_(True)
    ).first()
    if not assignment:
        log_action(
            db=db,
            user_id= current.user_id,action="NOTE_CREATION_FAILED",
            entity_type="nursing_notes" , entity_id=note_data.patient_id,
            result="FAILURE" , ip_address=request.client.host
        )
        raise HTTPException(status_code=403 , detail="Not assigned to this patient")
    new_note = NursingNote(
        patient_id= note_data.patient_id,
        nursing_by_id = current.user_id,
        blood_pressure = note_data.blood_pressure,
        heart_rate= note_data.heart_rate,
        respiratory_rate = note_data.respiratory_rate,
        pain_level = note_data.pain_level,
        temperature_celsius = note_data.temperature_celsius,
        oxygen_saturation= note_data.oxygen_saturation,
        care_notes = note_data.care_notes
    )
    db.add(new_note)
    db.commit()
    db.refresh(new_note)
    
    log_action(db=db, user_id=current.user_id, action="NOTE_CREATED",
                entity_type="nursing_notes", entity_id=new_note.id,
                result="SUCCESS", ip_address=request.client.host)
    
    return new_note

@router.get("/{patient_id}", response_model=List[NursingNoteResponse])
def get_nursing_notes(
    request: Request,
    patient_id: int,
    db: Session = Depends(get_db),
    current: TokenData = Depends(get_current_user)):

    if current.role not in ["Admin", "Doctor", "Nurse"]:
        log_action(db=db, user_id=current.user_id, action="NOTE_ACCESS_FAILED",
                   entity_type="nursing_notes", entity_id=patient_id,
                   result="FAILURE", ip_address=request.client.host)
        raise HTTPException(status_code=403, detail="Not authorized")

    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    if current.role in ["Doctor", "Nurse"]:
        assigned = db.query(PatientAssignment).filter(
            PatientAssignment.patient_id == patient_id,
            PatientAssignment.user_id == current.user_id,
            PatientAssignment.is_active.is_(True)
        ).first()
        if not assigned:
            log_action(db=db, user_id=current.user_id, action="NOTE_ACCESS_FAILED",
                       entity_type="nursing_notes", entity_id=patient_id,
                       result="FAILURE", ip_address=request.client.host)
            raise HTTPException(status_code=403, detail="Not assigned to this patient")

    nursing_notes = db.query(NursingNote).filter(NursingNote.patient_id == patient_id).order_by(NursingNote.created_at.desc()).all()
    log_action(db=db, user_id=current.user_id, action="NOTE_ACCESSED",
               entity_type="nursing_notes", entity_id=patient_id,
               result="SUCCESS", ip_address=request.client.host)

    return nursing_notes

