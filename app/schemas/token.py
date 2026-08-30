from pydantic import BaseModel
from typing import Literal

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    user_id: int
    role: Literal["SuperAdmin","Admin", "Doctor","Nurse"]