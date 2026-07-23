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