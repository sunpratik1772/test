"""Custom backend server — ADK API + static file serving for agent_outputs/."""

import os
from pathlib import Path

import uvicorn
from fastapi import Response
from fastapi.staticfiles import StaticFiles
from google.adk.cli.fast_api import get_fast_api_app
from app.config import rate_limit_tracker

# Resolve paths relative to this file's location
BASE_DIR = Path(__file__).parent
AGENTS_DIR = str(BASE_DIR / "app")
OUTPUTS_DIR = BASE_DIR / "agent_outputs"

# Ensure agent_outputs exists before mounting
OUTPUTS_DIR.mkdir(exist_ok=True)

fastapi_app = get_fast_api_app(
    agents_dir=AGENTS_DIR,
    allow_origins=["*"],
    web=False,
    host="127.0.0.1",
    port=8000,
)

# Serve agent_outputs/ at /files/ so the frontend download links work
fastapi_app.mount(
    "/files",
    StaticFiles(directory=str(OUTPUTS_DIR)),
    name="files",
)


@fastapi_app.get("/api/rate-limit-status")
async def get_rate_limit_status():
    """Return all rate-limit rotation events since last clear."""
    return {"events": rate_limit_tracker.get_all()}


@fastapi_app.delete("/api/rate-limit-status")
async def clear_rate_limit_status():
    """Clear rate-limit events (called by frontend at start of each new request)."""
    rate_limit_tracker.clear()
    return Response(status_code=204)


if __name__ == "__main__":
    uvicorn.run(fastapi_app, host="127.0.0.1", port=8000)
