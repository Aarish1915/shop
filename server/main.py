import sys
import os
from pathlib import Path

# Add current folder to sys.path so local modules resolve
SERVER_DIR = Path(__file__).resolve().parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

import uuid
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from b2b_router import b2b_router, init_b2b_db, get_b2b_db_path, b2b_executor
import sqlite3

# Lifespan: DB initialization and graceful drain of background executor (Gate 7-4)
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_b2b_db()
    yield
    b2b_executor.shutdown(wait=True, cancel_futures=False)

app = FastAPI(
    title="CleanNotes PrintFlow POS Server",
    description="Dedicated Xerox Shopkeeper B2B Counter API",
    version="3.0.0",
    lifespan=lifespan
)

# Sentry Error Tracking (Gate 7-7)
sentry_dsn = os.getenv("SENTRY_DSN")
if sentry_dsn:
    try:
        import sentry_sdk
        sentry_sdk.init(
            dsn=sentry_dsn,
            traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.1")),
            environment=os.getenv("DOCUMORPH_ENV", "production")
        )
    except Exception:
        pass

# Correlation ID Middleware (Gate 2-3)
@app.middleware("http")
async def correlation_id_middleware(request, call_next):
    corr_id = request.headers.get("X-Correlation-ID") or str(uuid.uuid4())
    request.state.correlation_id = corr_id
    response = await call_next(request)
    response.headers["X-Correlation-ID"] = corr_id
    return response

# Rate Limiting Middleware (Gate 2-2): 120 req/min per IP
_IP_REQUEST_HISTORY = defaultdict(list)
RATE_LIMIT_WINDOW_SEC = 60
MAX_REQUESTS_PER_WINDOW = 120

@app.middleware("http")
async def rate_limiting_middleware(request, call_next):
    client_ip = request.client.host if request.client else "127.0.0.1"
    # Exempt health probes from rate limits
    if request.url.path in ["/health", "/api/health"]:
        return await call_next(request)

    now = time.time()
    cutoff = now - RATE_LIMIT_WINDOW_SEC
    _IP_REQUEST_HISTORY[client_ip] = [t for t in _IP_REQUEST_HISTORY[client_ip] if t > cutoff]

    if len(_IP_REQUEST_HISTORY[client_ip]) >= MAX_REQUESTS_PER_WINDOW:
        return JSONResponse(
            status_code=429,
            content={"detail": "Rate limit exceeded. Please wait 60s before retrying."},
            headers={"Retry-After": "60"}
        )

    _IP_REQUEST_HISTORY[client_ip].append(now)
    return await call_next(request)

# Production Security Headers Middleware
@app.middleware("http")
async def add_security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    return response

def get_allowed_origins() -> list:
    raw = os.getenv("ALLOWED_ORIGINS", "")
    origins = [
        "http://localhost:5174",
        "http://127.0.0.1:5174",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "https://cleannotes.app",
        "https://cleannotes-pos.vercel.app"
    ]
    if raw:
        origins.extend([o.strip() for o in raw.split(",") if o.strip()])
    return origins

# Strict CORS: Allow Shopkeeper POS frontend & production origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_allowed_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition", "X-Total-Pages", "X-Elapsed-Seconds", "X-Savings-INR"]
)

from fastapi.responses import FileResponse, HTMLResponse

# Mount B2B Counter Router
app.include_router(b2b_router)

@app.get("/landing", response_class=HTMLResponse, tags=["Commercial Landing"])
async def serve_landing_page():
    landing_path = Path(__file__).resolve().parents[1] / "public" / "landing.html"
    if landing_path.exists():
        return FileResponse(landing_path)
    return HTMLResponse("<h1>CleanNotes PrintFlow POS</h1><p>Landing page not found.</p>", status_code=404)

@app.get("/admin", response_class=HTMLResponse, tags=["Central Counter Monitoring"])
async def serve_admin_dashboard():
    admin_path = Path(__file__).resolve().parents[1] / "public" / "admin.html"
    if admin_path.exists():
        return FileResponse(admin_path)
    return HTMLResponse("<h1>CleanNotes Command Center</h1><p>Admin dashboard not found.</p>", status_code=404)

@app.get("/health", tags=["Health & Status"])
@app.get("/api/health", tags=["Health & Status"])
async def health_check():
    """Shopkeeper server liveness and database probe."""
    db_ok = True
    try:
        with sqlite3.connect(get_b2b_db_path()) as conn:
            conn.execute("SELECT 1")
    except Exception:
        db_ok = False

    return {
        "status": "healthy" if db_ok else "degraded",
        "service": "CleanNotes PrintFlow POS Server",
        "database": "connected" if db_ok else "disconnected",
        "sentry": "configured" if sentry_dsn else "disabled",
        "port": 8001
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8001, reload=True)
