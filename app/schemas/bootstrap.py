from pydantic import BaseModel , EmailStr , field_validator
from app.core.validators import password_validator
class BootstrapCreate(BaseModel):
    full_name : str
    email : EmailStr
    password : str
    @field_validator('password')
    def validate_password(cls , v):
        return password_validator(v)