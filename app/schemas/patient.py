from pydantic import BaseModel , ConfigDict , field_validator
from datetime import date , datetime
from app.core.validators import height_validator , weight_validator
from typing import Optional

class PatientCreate(BaseModel):
    full_name : str
    dob: date
    height_cm : float
    weight_kg : float
    chief_complaint : str
    is_emergency : bool = False
    @field_validator('height_cm')
    def validate_height(cls, v):
        return height_validator(v)

    @field_validator('weight_kg')
    def validate_weight(cls, v):
        return weight_validator(v)

    @field_validator('dob')
    def validate_dob(cls , v:date) -> date:
        today = date.today()
        if v>today:
            raise ValueError('Date of birth cannot be in the future')
        if v.year < 1900:
            raise ValueError('Date of birth is not realistic')
        return v

class PatientResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id : int
    full_name : str
    dob : date
    height_cm: float
    weight_kg : float
    chief_complaint : str
    is_emergency : bool
    is_admitted : bool
    created_at : datetime

class PatientUpdate(BaseModel):
    height_cm : Optional[float] = None
    weight_kg : Optional[float] = None
    chief_complaint :Optional[str] = None
    is_admitted : Optional[bool] = None
    is_emergency : Optional[bool] = None
    @field_validator('height_cm')
    def validate_height(cls, v):
        return height_validator(v)

    @field_validator('weight_kg')
    def validate_weight(cls, v):
        return weight_validator(v)