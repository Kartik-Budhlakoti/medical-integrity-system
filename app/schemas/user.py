from pydantic import BaseModel , EmailStr , ConfigDict , field_validator

class UserCreate(BaseModel):
    full_name : str
    email : EmailStr
    password : str
    role_id : int
    @field_validator('password')
    def password_min_length(cls , v):
        if len(v) < 8:
            raise ValueError('Password must be at least 8 characters')
        if not any(c.isupper() for c in v):
            raise ValueError('Password must contain at least one uppercase letter')
        if not any(c.isdigit() for c in v):
            raise ValueError('Password must contain at least one number') 
        if not any(c in '!@#$%^&*()_+-=[]{}|;:,.<>?' for c in v):
            raise ValueError('Password must contain at least one special character')
        return v

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

    