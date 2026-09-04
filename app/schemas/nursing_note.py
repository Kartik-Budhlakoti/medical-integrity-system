from pydantic import BaseModel, ConfigDict , field_validator
from datetime import datetime
from typing import Optional

class NursingNoteCreate(BaseModel):
    patient_id: int
    blood_pressure : Optional[str] = None
    heart_rate: Optional[int] = None
    respiratory_rate: Optional[int] = None
    pain_level: Optional[int] = None
    temperature_celsius: Optional[float] = None
    oxygen_saturation: Optional[int] = None
    care_notes: str
    @field_validator('care_notes')
    def validate_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError('Care notes cannot be empty or whitespace')
        return v
    @field_validator('pain_level')
    def validate_pain_level(cls, v: Optional[int]):
        if v is not None and not (0 <= v <= 10):
            raise ValueError('Pain level must be between 0 and 10')
        return v

    @field_validator('heart_rate')
    def validate_heart_rate(cls, v: Optional[int]):
        if v is not None and not (0 <= v <= 300):
            raise ValueError('Heart rate must be between 0 and 300')
        return v

    @field_validator('respiratory_rate')
    def validate_respiratory_rate(cls, v: Optional[int]):
        if v is not None and not (0 <= v <= 60):
            raise ValueError('Respiratory rate must be between 0 and 60')
        return v

    @field_validator('oxygen_saturation')
    def validate_oxygen_saturation(cls, v: Optional[int]):
        if v is not None and not (0 <= v <= 100):
            raise ValueError('Oxygen saturation must be between 0 and 100')
        return v

    @field_validator('temperature_celsius')
    def validate_temperature(cls, v: Optional[float]):
        if v is not None and not (25 <= v <= 45):
            raise ValueError('Temperature must be between 25 and 45 celsius')
        return v


class NursingNoteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    patient_id: int
    nursing_by_id : int
    blood_pressure : Optional[str] = None
    heart_rate: Optional[int] = None
    respiratory_rate: Optional[int] = None
    pain_level: Optional[int] = None
    temperature_celsius: Optional[float] = None
    oxygen_saturation: Optional[int] = None
    care_notes: str
    created_at: datetime