from fastapi import FastAPI
from app.routers.user import router as user_router
from app.routers.auth import router as auth_router
from app.routers.bootstrap import router as bootstrap_router
from app.routers.patient import router as patient_router 
from app.routers.assignment import router as assignment_router
from app.routers.file import router as file_router
from app.routers.treatment_note import router as treatment_note_router
from slowapi import Limiter , _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded 
import app.models


app = FastAPI(
    title="Medical Integrity System",
    version="1.0.0"
)
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.include_router(user_router)

app.include_router(auth_router)

app.include_router(bootstrap_router)

app.include_router(patient_router)

app.include_router(assignment_router)

app.include_router(file_router)

app.include_router(treatment_note_router)


@app.get("/health")
def health_check():
    return {"status" : "ok"}

