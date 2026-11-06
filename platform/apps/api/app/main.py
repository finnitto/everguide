from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from redis import Redis
from app.config import settings
from app.database import database_is_ready
from app.routers.providers import router as directory_router
from app.routers.discovery import router as discovery_router
from app.routers.enrichment import router as enrichment_router
from app.routers.website_discovery import router as website_discovery_router

app = FastAPI(title=settings.app_name, version=settings.app_version, description="Everguide directory and provider management API")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.include_router(directory_router)
app.include_router(discovery_router)
app.include_router(enrichment_router)
app.include_router(website_discovery_router)

@app.get("/health", tags=["health"])
def health(): return {"status":"ok","service":"everguide-api","version":settings.app_version}

@app.get("/health/ready", tags=["health"])
def readiness():
    try:
        database_is_ready(); Redis.from_url(settings.redis_url,socket_connect_timeout=2).ping()
    except Exception as exc: raise HTTPException(status_code=503,detail=f"Dependency not ready: {type(exc).__name__}")
    return {"status":"ready","database":"connected","postgis":"available","redis":"connected"}

@app.get("/api/v1")
def api_root(): return {"name":settings.app_name,"version":settings.app_version,"message":"Everguide core directory API is running."}
