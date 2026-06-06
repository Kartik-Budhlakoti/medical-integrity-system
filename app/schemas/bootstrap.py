from pydantic import BaseModel , EmailStr
class BootstrapCreate(BaseModel):
    full_name : str
    email : EmailStr
    password : str