from fastapi import FastAPI
from app.routers.user import router as user_router
from app.routers.auth import router as auth_router
from app.routers.bootstrap import router as bootstrap_router
from app.routers.patient import router as patient_router
from app.routers.assignment import router as assignment_router
from app.routers.file import router as file_router
from app.routers.treatment_note import router as treatment_note_router
from app.routers.nursing_note import router as nursing_note_router
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.middleware.base import BaseHTTPMiddleware
import app.models
from app.core.limiter import limiter

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-XSS-Protection": "1; mode=block",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "Content-Security-Policy": "default-src 'self'",
    "Referrer-Policy": "strict-origin-when-cross-origin",
}

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self , request , call_next) :
        response = await call_next(request)
        for header , value in SECURITY_HEADERS.items():
            response.headers[header] = value
        return response

app = FastAPI(
    title="Medical Integrity System",
    version="1.0.0"
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SecurityHeadersMiddleware)

app.include_router(user_router)
app.include_router(auth_router)
app.include_router(bootstrap_router)
app.include_router(patient_router)
app.include_router(assignment_router)
app.include_router(file_router)
app.include_router(treatment_note_router)
app.include_router(nursing_note_router)

@app.get("/health")
def health_check():
    return {"status": "ok"}