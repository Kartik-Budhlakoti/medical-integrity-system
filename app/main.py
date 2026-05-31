from fastapi import FastAPI

app = FastAPI(
    title="Medical Integrity System",
    version="1.0.0"
)

@app.get("/health")
def health_check():
    return {"status" : "ok"}
