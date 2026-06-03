from fastapi import FastAPI
from app.routers.user import router as user_router
from app.routers.auth import router as auth_router
app = FastAPI(
    title="Medical Integrity System",
    version="1.0.0"
)

app.include_router(user_router)

app.include_router(auth_router)

@app.get("/health")
def health_check():
    return {"status" : "ok"}

