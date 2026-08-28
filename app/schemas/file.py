from pydantic import BaseModel, ConfigDict , field_validator
from datetime import datetime
from typing import Optional

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

class AllFileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    patient_id: int
    file_type: str
    file_name: str
    uploaded_by_id: int
    is_active: bool
    invalidation_reason: Optional[str] = None
    invalidated_by_id: Optional[int] = None
    invalidated_at: Optional[datetime] = None
    verified_at: Optional[datetime] = None
    created_at: datetime

class FileInvalidate(BaseModel):
    invalidation_reason: str
    @field_validator('invalidation_reason')
    def validate_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError('Invalidation reason cannot be empty or whitespace')
        return v