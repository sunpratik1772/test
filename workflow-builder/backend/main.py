"""
Workflow Builder — FastAPI backend
Endpoints:
  GET  /api/node-types          → node catalog + categories
  POST /api/workflow/execute    → SSE stream of node execution events
  GET  /api/health              → liveness check
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from executor import execute_workflow
from node_catalog import CATEGORIES, NODE_CATALOG

load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")
API_KEY = os.getenv("GOOGLE_API_KEY", "")

app = FastAPI(title="Surveillance Workflow Builder API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Health ───────────────────────────────────────────────────────────────────

@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "api_key_set": bool(API_KEY)}


# ── Node catalog ─────────────────────────────────────────────────────────────

@app.get("/api/node-types")
def node_types() -> dict:
    return {"categories": CATEGORIES, "nodes": NODE_CATALOG}


# ── Workflow execution ───────────────────────────────────────────────────────

class WorkflowPayload(BaseModel):
    nodes: list[dict]
    edges: list[dict]


@app.post("/api/workflow/execute")
def workflow_execute(payload: WorkflowPayload) -> StreamingResponse:
    if not API_KEY:
        raise HTTPException(status_code=503, detail="GOOGLE_API_KEY not configured")

    workflow = {"nodes": payload.nodes, "edges": payload.edges}

    def event_stream():
        for event in execute_workflow(workflow, API_KEY):
            yield f"data: {json.dumps(event)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
