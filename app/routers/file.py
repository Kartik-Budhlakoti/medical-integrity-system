from fastapi import APIRouter, Depends, HTTPException, Request, File, UploadFile
from sqlalchemy.orm import Session ,joinedload
from app.database import get_db
from app.schemas.file import FileResponse, FileInvalidate , AllFileResponse
from app.core.audit import log_action
from app.core.dependencies import get_current_user
from app.core.integrity import compute_sha256
from app.schemas.token import TokenData
from app.models.file import File as FileModel, FileHash
from app.models.patient import Patient
from app.models.patient_assignment import PatientAssignment
from datetime import datetime, timezone
import os
import uuid
from typing import Annotated , List
from fastapi import Form , Response
from urllib.parse import quote
from app.core.limiter import limiter


UPLOAD_DIR= os.getenv("UPLOAD_DIR" , "uploads")
os.makedirs(UPLOAD_DIR , exist_ok=True)

MAX_FILE_SIZE = 50 * 1024 * 1024
ALLOWED_EXTENSIONS = {".dcm", ".jpg" , ".jpeg" , ".png" , ".pdf"}

router = APIRouter(prefix="/files" , tags=["files"])

@router.post("/upload" , response_model=FileResponse)
@limiter.limit("10/minute")
def upload_file(
    request: Request,
    patient_id : Annotated[int , Form()],
    file_type : Annotated[str , Form()],
    file: UploadFile = File(...), 
    db : Session= Depends (get_db) , 
    current : TokenData = Depends(get_current_user)
):
    if current.role not in ["Admin" , "Doctor" , "Nurse"]:
        log_action(
            db=db,
            user_id= current.user_id,
            action= "FILE_UPLOAD_FAILED",
            entity_type = "files",
            entity_id = patient_id, 
            result= "FAILURE",
            ip_address=request.client.host
        )
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
            log_action(db=db, user_id=current.user_id, action="FILE_UPLOAD_FAILED",
                    entity_type="files", entity_id=patient_id,
                    result="FAILURE", ip_address=request.client.host)
            raise HTTPException(status_code=403, detail="Not assigned to this patient")
     

    file_bytes = file.file.read()
    if len(file_bytes) > MAX_FILE_SIZE:
            raise HTTPException(status_code=413, detail="File too large. Maximum 50MB.")
    
    original_filename = file.filename
    if not original_filename:
        raise HTTPException(status_code=400, detail="Filename required")
    file_extension = os.path.splitext(original_filename)[1].lower()

    if file_extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="File type not allowed")
    
    unique_filename = f"{uuid.uuid4()}{file_extension}"
    file_path = os.path.join(UPLOAD_DIR, unique_filename)

    with open(file_path , "wb") as f :
        f.write(file_bytes)

    hash_value = compute_sha256(file_bytes)
    try:
        file_record = FileModel(
            patient_id = patient_id,
            uploaded_by_id = current.user_id,
            file_type = file_type,
            file_name = original_filename,
            file_path = file_path
        )
        db.add(file_record)
        db.flush()

        file_hash =FileHash(
            file_id = file_record.id,
            hash_value = hash_value
        )
        db.add(file_hash)
        db.commit()
        db.refresh(file_record)
    except Exception:
        db.rollback()
        if os.path.exists(file_path):
            os.remove(file_path)
        raise HTTPException(status_code=500 , detail="File upload failed, please try again")
    log_action(
            db=db,
            user_id= current.user_id,
            action= "FILE_UPLOADED",
            entity_type = "files",
            entity_id =file_record.id, 
            result= "SUCCESS",
            ip_address=request.client.host
        )
    return file_record

@router.get("/{file_id}" )
@limiter.limit("20/minute")
def get_file(request:Request ,file_id : int, 
    db : Session= Depends (get_db) , 
    current : TokenData = Depends(get_current_user)):
     
    if current.role not in ["Admin" , "Doctor" , "Nurse"]:
        log_action(
            db=db,
            user_id= current.user_id,
            action= "FILE_ACCESS_DENIED",
            entity_type = "files",
            entity_id =file_id, 
            result= "FAILURE",
            ip_address=request.client.host
        )
        raise HTTPException(status_code=403, detail="Not authorized")
    
    file_record = db.query(FileModel).filter(FileModel.id == file_id).first()
    if not file_record:
        raise HTTPException(status_code=404, detail="File not found")  
    
    if not file_record.is_active:
        log_action(db=db, user_id=current.user_id, action="FILE_ACCESS_DENIED",
                entity_type="files", entity_id=file_id,
                result="FAILURE", ip_address=request.client.host)
        raise HTTPException(status_code=403, detail="File is invalidated") 
    
    if current.role in ["Doctor", "Nurse"]:
        assigned = db.query(PatientAssignment).filter(
            PatientAssignment.patient_id == file_record.patient_id,
            PatientAssignment.user_id == current.user_id,
            PatientAssignment.is_active.is_(True)
        ).first()
        if not assigned:
            log_action(db=db, user_id=current.user_id, action="FILE_ACCESS_DENIED",
                    entity_type="files", entity_id=file_record.id,
                    result="FAILURE", ip_address=request.client.host)
            raise HTTPException(status_code=403, detail="Not assigned to this patient")
        
    with open(file_record.file_path , "rb") as f:    
        file_bytes = f.read()

    hash_value = compute_sha256(file_bytes)

    stored_hash = db.query(FileHash).filter(FileHash.file_id == file_record.id).first()
    if not stored_hash:
        log_action(
                    db=db,
                    user_id= current.user_id,
                    action= "FILE_INTEGRITY_RECORD_MISSING",
                    entity_type = "files",
                    entity_id =file_record.id, 
                    result= "FAILURE",
                    ip_address=request.client.host
                )
        raise HTTPException(status_code=500, detail="File hash not found")
    
    if hash_value != stored_hash.hash_value : 
        file_record.is_active = False
        db.commit()
        log_action(
            db=db,
            user_id= current.user_id,
            action= "TAMPER_DETECTED",
            entity_type = "files",
            entity_id =file_record.id, 
            result= "FAILURE",
            ip_address=request.client.host
        )
        raise HTTPException(status_code=403, detail="File integrity verification failed")
    
    stored_hash.verified_at = datetime.now(timezone.utc)
    db.commit()
    log_action(
            db=db,
            user_id= current.user_id,
            action= "FILE_ACCESSED",
            entity_type = "files",
            entity_id =file_record.id, 
            result= "SUCCESS",
            ip_address=request.client.host
        )
    safe_filename = quote(file_record.file_name)
    return Response(
        content=file_bytes,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{safe_filename}"}
    )

@router.get("/patient/{patient_id}", response_model=List[AllFileResponse])
def get_all_files(request: Request ,patient_id:int,  db : Session= Depends (get_db) , 
    current : TokenData = Depends(get_current_user)):
    if current.role not in ["Admin" , "Doctor" , "Nurse"] :
        log_action(
                   db=db,
                   user_id= current.user_id,
                   action= "FILE_ACCESS_DENIED",
                   entity_type = "files",
                   entity_id =patient_id, 
                   result= "FAILURE",
                   ip_address=request.client.host
               )
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
            log_action(db=db, user_id=current.user_id, action="FILE_ACCESS_DENIED",
                    entity_type="files", entity_id=patient_id,
                    result="FAILURE", ip_address=request.client.host)
            raise HTTPException(status_code=403, detail="Not assigned to this patient")
    file_records = db.query(FileModel).filter(FileModel.patient_id == patient_id).options(joinedload(FileModel.file_hash)).order_by(FileModel.created_at.desc()).all()
    log_action(db=db, user_id=current.user_id, action="FILES_LISTED",
            entity_type="files", entity_id=patient_id,
            result="SUCCESS", ip_address=request.client.host)
    return file_records
  
@router.post("/{file_id}/invalidate")
def file_invalidation(request: Request , file_id:int, invalidation_data:FileInvalidate, db:Session = Depends(get_db), current : TokenData = Depends(get_current_user)):
    if current.role != "Admin":
        log_action(db=db, user_id=current.user_id, action="FILE_INVALIDATION_FAILED",
                   entity_type="files", entity_id=file_id,
                   result="FAILURE", ip_address=request.client.host)
        raise HTTPException(status_code=403, detail="Not authorized")
    
    file_record = db.query(FileModel).filter(FileModel.id == file_id).first()
    if not file_record:
        raise HTTPException(status_code=404, detail="File not found")
    
    if not file_record.is_active:
        log_action(db=db, user_id=current.user_id, action="FILE_INVALIDATION_FAILED",
                entity_type="files", entity_id=file_id,
                result="FAILURE", ip_address=request.client.host)
        raise HTTPException(status_code=400, detail="File is already invalidated")

    file_record.is_active = False
    file_record.invalidation_reason = invalidation_data.invalidation_reason
    file_record.invalidated_by_id = current.user_id
    file_record.invalidated_at = datetime.now(timezone.utc)
    db.commit()
    
    log_action(db=db, user_id=current.user_id, action="FILE_INVALIDATED",
                   entity_type="files", entity_id=file_id,
                   result="SUCCESS", ip_address=request.client.host)
    return {"message": "File invalidated successfully"}

