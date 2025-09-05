import os
import secrets
from datetime import datetime, timedelta
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import APIKeyHeader
from fastapi.middleware.cors import CORSMiddleware
from pydantic_settings import BaseSettings
from sqlalchemy import create_engine, text
from fastapi.responses import JSONResponse

# ===== SETTINGS =====
class Settings(BaseSettings):
    DATABASE_URL: str
    API_KEY: str
    CACHE_TTL: int = 60  # seconds
    class Config:
        env_file = ".env"

settings = Settings()

engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=True)

def require_api_key(api_key: str = Depends(api_key_header)):
    if not secrets.compare_digest(api_key, settings.API_KEY):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API Key"
        )
    return True

# ===== CORS =====
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
origins = [
    "https://dynastypulse.com",  # Your WordPress site URL
    # Add other allowed origins if needed
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,  # Change in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ===== CACHE =====
cache_data = None
cache_expiry = None

def fetch_view_data(limit: int):
    """Pull fresh data from the MySQL view."""
    with engine.connect() as conn:
        q = text("SELECT * FROM VORP_Latest LIMIT :limit")
        result = conn.execute(q, {"limit": limit})
        return [dict(r._mapping) for r in result]

def get_cached_data(limit: int):
    """Return cached data if valid, else refresh."""
    global cache_data, cache_expiry
    now = datetime.utcnow()
    if cache_data and cache_expiry and now < cache_expiry:
        return cache_data
    data = fetch_view_data(limit)
    cache_data = data
    cache_expiry = now + timedelta(seconds=settings.CACHE_TTL)
    return data

# ===== STARTUP PRE-CACHE =====
@app.on_event("startup")
def preload_cache():
    global cache_data, cache_expiry
    cache_data = fetch_view_data(100)  # Preload with 100 rows
    cache_expiry = datetime.utcnow() + timedelta(seconds=settings.CACHE_TTL)
    print(f"[CACHE] Preloaded {len(cache_data)} rows at startup.")

# ===== ROUTES =====
@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/view")
def read_view(limit: int = 100, _=Depends(require_api_key)):
    try:
        rows = get_cached_data(limit)
        return {"rows": rows[:limit]}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/")
def root():
    return {"message": "FastAPI running. Use /view with API key to get data."}
