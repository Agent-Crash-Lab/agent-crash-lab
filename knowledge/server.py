"""Internal-only search endpoint, with a warm model shared by bounded CPU requests."""

import os
import secrets
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from knowledge.embedding import Embedder
from knowledge.retrieval import search, status


def internal(x_internal_token: str = Header(default="")):
    expected = os.environ.get("INTERNAL_API_TOKEN", "")
    if not expected:
        raise HTTPException(503, "INTERNAL_TOKEN_NOT_CONFIGURED")
    if not secrets.compare_digest(expected, x_internal_token):
        raise HTTPException(401, "UNAUTHORIZED")


@asynccontextmanager
async def lifespan(app):
    app.state.model = Embedder()
    yield


app = FastAPI(lifespan=lifespan)


class Search(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    query: str = Field(min_length=2, max_length=1000)
    target_type: Literal["COMMON", "PURCHASE", "PRODUCTION", "QUALITY"] = "COMMON"
    limit: int = Field(default=3, ge=1, le=5)
    source_type: Literal[
        "ALL", "RESEARCH", "INCIDENT", "TECHNICAL", "PROJECT_POLICY"
    ] = "ALL"
    risk_type: str | None = Field(default=None, min_length=1, max_length=64)
    evidence_domain: Literal["MANUFACTURING", "AGENTIC"] | None = None


@app.get("/health")
def health():
    return {"status": "UP", "model_loaded": True}


@app.get("/internal/knowledge/status", dependencies=[Depends(internal)])
def knowledge_status():
    return status()


@app.post("/internal/knowledge/search", dependencies=[Depends(internal)])
def knowledge_search(body: Search):
    try:
        return search(
            app.state.model,
            body.query,
            body.target_type,
            body.limit,
            body.source_type,
            body.risk_type,
            body.evidence_domain,
        )
    except ValueError as exc:
        raise HTTPException(503, str(exc)) from None
