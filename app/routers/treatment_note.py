from fastapi import APIRouter, Request, Depends, HTTPException
from sqlalchemy.orm import Session
from app.models.treatment_note import TreatmentNote
from app.schemas.treatment_note import TreatmentNoteCreate, TreatmentNoteResponse
from app.core.dependencies import get_current_user
from app.schemas.token import TokenData
from app.database import get_db
from app.models.patient import Patient
from app.models.patient_assignment import PatientAssignment
from app.core.audit import log_action
from typing import List

router = APIRouter(prefix="/notes", tags=["notes"])

@router.post("/create", response_model=TreatmentNoteResponse)
def create_treatment_note(
    request: Request,
    note_data: TreatmentNoteCreate,
    db: Session = Depends(get_db), current: TokenData = Depends(get_current_user)):
    if current.role != "Doctor":
        log_action(db=db, user_id=current.user_id, action="NOTE_CREATION_FAILED",
                   entity_type="treatment_notes", entity_id=note_data.patient_id,
                   result="FAILURE", ip_address=request.client.host)
        raise HTTPException(status_code=403, detail="Not authorized")

    patient = db.query(Patient).filter(Patient.id == note_data.patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    assigned = db.query(PatientAssignment).filter(
        PatientAssignment.patient_id == note_data.patient_id,
        PatientAssignment.user_id == current.user_id,
        PatientAssignment.is_active.is_(True)
    ).first()
    if not assigned:
        log_action(db=db, user_id=current.user_id, action="NOTE_CREATION_FAILED",
                   entity_type="treatment_notes", entity_id=note_data.patient_id,
                   result="FAILURE", ip_address=request.client.host)
        raise HTTPException(status_code=403, detail="Not assigned to this patient")

    new_note = TreatmentNote(
        patient_id= note_data.patient_id,
        treatment_by_id = current.user_id,
        condition_update= note_data.condition_update,
        completed_procedures= note_data.completed_procedures,
        ongoing_treatments= note_data.ongoing_treatments,
        medications = note_data.medications,
        observations = note_data.observations,
        orders=note_data.orders
    )
    db.add(new_note)
    db.commit()
    db.refresh(new_note)

    log_action(db=db, user_id=current.user_id, action="NOTE_CREATED",
               entity_type="treatment_notes", entity_id=new_note.id,
               result="SUCCESS", ip_address=request.client.host)

    return new_note

@router.get("/{patient_id}", response_model=List[TreatmentNoteResponse])
def get_treatment_notes(
    request: Request,
    patient_id: int,
    db: Session = Depends(get_db),
    current: TokenData = Depends(get_current_user)):

    if current.role not in ["Admin", "Doctor", "Nurse"]:
        log_action(db=db, user_id=current.user_id, action="NOTE_ACCESS_FAILED",
                   entity_type="treatment_notes", entity_id=0,
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
                       entity_type="treatment_notes", entity_id=patient_id,
                       result="FAILURE", ip_address=request.client.host)
            raise HTTPException(status_code=403, detail="Not assigned to this patient")

    treatment_notes = db.query(TreatmentNote).filter(TreatmentNote.patient_id == patient_id).all()
    log_action(db=db, user_id=current.user_id, action="NOTE_ACCESSED",
               entity_type="treatment_notes", entity_id=patient_id,
               result="SUCCESS", ip_address=request.client.host)

    return treatment_notes
