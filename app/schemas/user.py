from pydantic import BaseModel , EmailStr , ConfigDict , field_validator, model_validator
from app.core.validators import password_validator
class UserCreate(BaseModel):
    full_name : str
    email : EmailStr
    password : str
    role_id : int
    @field_validator('password')
    def validate_password(cls , v):
        return password_validator(v)

class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id : int
    full_name : str
    email: EmailStr
    role_id : int
    is_active : bool

class UserLogin(BaseModel):
    email : EmailStr
    password : str

class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str
    
    @field_validator('new_password')
    def validate_new_password(cls , v):
        return password_validator(v)
    
    @model_validator(mode='after')
    def check_password_differ(self):
        if self.old_password == self.new_password:
            raise ValueError('New password must be different from current password')
        return self

class ChangePasswordResponse(BaseModel):
    message: str