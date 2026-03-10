"""FastAPI entry point for NetBird MSP Appliance."""

import logging
import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.database import init_db
from app.limiter import limiter
from app.routers import auth, customers, deployments, monitoring, settings, users

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------
app = FastAPI(
    title="NetBird MSP Appliance",
    description="Multi-tenant NetBird management platform for MSPs",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

# Attach limiter to app state and register the 429 exception handler
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS — restrict to explicitly configured origins only.
# Set ALLOWED_ORIGINS in .env as a comma-separated list of allowed origins,
# e.g. ALLOWED_ORIGINS=https://myapp.example.com
# If unset, no cross-origin requests are allowed (same-origin only).
_raw_origins = os.environ.get("ALLOWED_ORIGINS", "")
_allowed_origins = [o.strip() for o in _raw_origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

# ---------------------------------------------------------------------------
# Security headers middleware
# ---------------------------------------------------------------------------
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    """Attach standard security headers to every response."""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------
app.include_router(auth.router, prefix="/api/auth", tags=["Authentication"])
app.include_router(settings.router, prefix="/api/settings", tags=["Settings"])
app.include_router(customers.router, prefix="/api/customers", tags=["Customers"])
app.include_router(deployments.router, prefix="/api/customers", tags=["Deployments"])
app.include_router(monitoring.router, prefix="/api/monitoring", tags=["Monitoring"])
app.include_router(users.router, prefix="/api/users", tags=["Users"])

# ---------------------------------------------------------------------------
# Static files — serve the frontend SPA
# ---------------------------------------------------------------------------
STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
if os.path.isdir(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Serve index.html at root — inject cache-busting version into static asset URLs
# so the browser always loads fresh JS/CSS after a container update.
from fastapi.responses import FileResponse, HTMLResponse
from app.services import update_service

_STATIC_ASSETS = (
    '"/static/js/app.js"',
    '"/static/js/i18n.js"',
    '"/static/css/styles.css"',
)

def _cache_bust_index(html: str, version: str) -> str:
    # Inject version as a global JS variable so i18n.js can bust lang file caches too
    html = html.replace("</head>", f'<script>window.STATIC_VERSION="{version}";</script>\n</head>', 1)
    for asset in _STATIC_ASSETS:
        busted = asset.rstrip('"') + f'?v={version}"'
        html = html.replace(asset, busted)
    return html


@app.get("/", include_in_schema=False)
async def serve_index():
    """Serve the main dashboard with cache-busted static asset URLs."""
    index_path = os.path.join(STATIC_DIR, "index.html")
    if not os.path.isfile(index_path):
        return JSONResponse({"message": "NetBird MSP Appliance API is running."})
    version = update_service.get_current_version().get("commit", "unknown")
    html = open(index_path, encoding="utf-8").read()
    html = _cache_bust_index(html, version)
    return HTMLResponse(content=html, headers={"Cache-Control": "no-cache"})


# ---------------------------------------------------------------------------
# Health endpoint (unauthenticated)
# ---------------------------------------------------------------------------
@app.get("/api/health", tags=["Health"])
async def health_check():
    """Simple health check endpoint for Docker HEALTHCHECK."""
    return {"status": "ok", "service": "netbird-msp-appliance"}


# ---------------------------------------------------------------------------
# Startup event
# ---------------------------------------------------------------------------
@app.on_event("startup")
async def startup_event():
    """Initialize database tables on startup."""
    logger.info("Starting NetBird MSP Appliance...")
    init_db()
    logger.info("Database initialized.")
