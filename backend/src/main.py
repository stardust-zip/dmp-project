from fastapi import FastAPI

app = FastAPI(
    title="DMP Smart City AI Platform", description="Forcasting, Anomaly Detection"
)


@app.get("/health")
def health_check():
    """Satisfies the Docker Compose healthcheck"""
    return {"status": "healthy", "service": "dmp-backend"}


@app.get("/")
def root():
    return {"message": "DMP Backend is running. Visit /docs to view the Swagger UI."}
