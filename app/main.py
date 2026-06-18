from fastapi import FastAPI
from app.routers.user import router as user_router
from app.routers.auth import router as auth_router
from app.routers.bootstrap import router as bootstrap_router
from app.routers.patient import router as patient_router 
from app.routers.assignment import router as assignment_router
import app.models

app = FastAPI(
    title="Medical Integrity System",
    version="1.0.0"
)

app.include_router(user_router)

app.include_router(auth_router)

app.include_router(bootstrap_router)

app.include_router(patient_router)

app.include_router(assignment_router)

@app.get("/health")
def health_check():
    return {"status" : "ok"}

