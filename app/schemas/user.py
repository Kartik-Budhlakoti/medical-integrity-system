from pydantic import BaseModel , EmailStr , ConfigDict

class UserCreate(BaseModel):
    full_name : str
    email : EmailStr
    password : str
    role_id : int

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

    