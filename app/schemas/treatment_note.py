from pydantic import BaseModel, ConfigDict
from datetime import datetime
from typing import Optional

class TreatmentNoteCreate(BaseModel):
    patient_id: int
    condition_update: str
    completed_procedures: Optional[str] = None
    ongoing_treatments: Optional[str] = None
    medications: str
    observations: Optional[str] = None
    orders: str

class TreatmentNoteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    patient_id: int
    treatment_by_id: int
    condition_update: str
    completed_procedures: Optional[str] = None
    ongoing_treatments: Optional[str] = None
    medications: str
    observations: Optional[str] = None
    orders: str
    created_at: datetime