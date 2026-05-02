"""
Global-Pulse – FastAPI Application Entry Point
"""

from __future__ import annotations

import logging

import os

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import api_keys, forecasting, maritime, news, weather

# ──────────────────────────────────────────────────────────────
#  Logging
# ──────────────────────────────────────────────────────────────

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.JSONRenderer(),
    ]
)
logging.basicConfig(level=logging.INFO)

# ──────────────────────────────────────────────────────────────
#  Application
# ──────────────────────────────────────────────────────────────

app = FastAPI(
    title="Global-Pulse DaaS API",
    description=(
        "Data-as-a-Service platform providing real-time maritime shipping data, "
        "weather observations, news feeds, and AI-powered delay forecasts for "
        "global shipping routes."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

_cors_origins_env = os.getenv("CORS_ALLOWED_ORIGINS", "*")
_cors_origins = [o.strip() for o in _cors_origins_env.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ──────────────────────────────────────────────────────────────
#  Routers
# ──────────────────────────────────────────────────────────────

app.include_router(api_keys.router,    prefix="/v1/api-keys",    tags=["API Key Management"])
app.include_router(maritime.router,    prefix="/v1/maritime",    tags=["Maritime"])
app.include_router(weather.router,     prefix="/v1/weather",     tags=["Weather"])
app.include_router(news.router,        prefix="/v1/news",        tags=["News"])
app.include_router(forecasting.router, prefix="/v1/forecasting", tags=["Forecasting"])


@app.get("/", tags=["Health"])
async def root() -> dict:
    return {"service": "Global-Pulse DaaS API", "version": "1.0.0", "status": "ok"}


@app.get("/health", tags=["Health"])
async def health() -> dict:
    return {"status": "ok"}
