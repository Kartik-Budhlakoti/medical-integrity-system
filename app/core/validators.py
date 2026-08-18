def password_validator(v : str) -> str:
    if len(v) < 8:
        raise ValueError('Password must be at least 8 characters')
    if not any(c.isupper() for c in v):
        raise ValueError('Password must contain at least one uppercase letter')
    if not any(c.isdigit() for c in v):
        raise ValueError('Password must contain at least one number') 
    if not any(c in '!@#$%^&*()_+-=[]{}|;:,.<>?' for c in v):
        raise ValueError('Password must contain at least one special character')
    if len(v.encode('utf-8')) > 72:
        raise ValueError('Password length is more than maximum size')
    return v
def height_validator(v: float) -> float:
    if v is None:
        return v
    if not (30 <= v <= 250):
        raise ValueError('Height must be between 30 and 250 cm')
    return v

def weight_validator(v: float) -> float:
    if v is None:
        return v
    if not (5.0 <= v <= 300):
        raise ValueError('Weight must be between 5.0 and 300 kg')
    return v