from pydantic import BaseModel, ConfigDict
from datetime import datetime

class AssignmentCreate(BaseModel):
    patient_id : int
    user_id : int

class AssignmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id : int
    user_id : int
    patient_id : int
    assigned_by_id : int
    is_active : bool
    created_at : datetime