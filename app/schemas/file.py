from pydantic import BaseModel, ConfigDict
from datetime import datetime

class FileUpload(BaseModel):
    patient_id: int
    file_type: str

class FileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    patient_id: int
    file_type: str
    file_name: str
    file_path: str
    uploaded_by_id: int
    is_active: bool
    created_at: datetime

class FileInvalidate(BaseModel):
    invalidation_reason: str