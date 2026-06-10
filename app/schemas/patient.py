from pydantic import BaseModel , ConfigDict
from datetime import date , datetime
from typing import Optional

class PatientCreate(BaseModel):
    full_name : str
    date_of_birth : date
    height_cm : float
    weight_kg : float
    chief_complaint : str
    is_emergency : bool = False

class PatientResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id : int
    full_name : str
    date_of_birth : date
    height_cm : float
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