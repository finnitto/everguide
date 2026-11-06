from fastapi import FastAPI, HTTPException
from redis import Redis
from app.config import settings
from app.database import database_is_ready

app = FastAPI(title=settings.app_name, version=settings.app_version,
              description="Everguide application API")

@app.get("/health", tags=["health"])
def health():
    return {"status": "ok", "service": "everguide-api", "version": settings.app_version}

@app.get("/health/ready", tags=["health"])
def readiness():
    try:
        database_is_ready()
        Redis.from_url(settings.redis_url, socket_connect_timeout=2).ping()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Dependency not ready: {type(exc).__name__}")
    return {"status": "ready", "database": "connected", "postgis": "available", "redis": "connected"}

@app.get("/api/v1", tags=["system"])
def api_root():
    return {"name": settings.app_name, "version": settings.app_version,
            "message": "Everguide API foundation is running."}
