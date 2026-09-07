"""
AI Database Query Assistant - FastAPI Backend
Proper REST API product for natural language → SQL
"""

from __future__ import annotations

import io
import math
import os
import sys
from datetime import datetime, date
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# Make utils importable
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

from utils.db_manager import DatabaseManager, DIALECT_CONFIG
from utils.llm_client import LLMClient, DEFAULT_XAI_URL, DEFAULT_MODEL_XAI

# Load environment variables from a local .env file (never committed, never
# sent to the browser). This is where the real LLM API key lives now.
# override=True ensures values in .env always win, even if a stale/empty
# LLM_API_KEY happens to already be set in the shell environment.
load_dotenv(ROOT.parent / ".env", override=True)

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------
app = FastAPI(
    title="AI DB Query Assistant API",
    description="Natural language to SQL over multiple databases",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global managers
DATA_DIR = ROOT.parent / "data"
DATA_DIR.mkdir(exist_ok=True)
db_manager = DatabaseManager(str(DATA_DIR / "connections.json"))

# ---------------------------------------------------------------------------
# LLM configuration
# ---------------------------------------------------------------------------
# The API key is read ONLY from the server-side .env file (see .env.example)
# via environment variables. It is never accepted from the browser and never
# returned in any API response, so end users of the app can't see or change
# it. To change the key or provider, edit .env / these defaults in code and
# restart the server.
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "openai/gpt-oss-20b")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")

llm_client = LLMClient(
    provider=LLM_PROVIDER,
    base_url=LLM_BASE_URL,
    model=LLM_MODEL,
    api_key=LLM_API_KEY,
)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------
class ConnectionCreate(BaseModel):
    name: str
    dialect: str = "postgresql"
    host: str = "localhost"
    port: Optional[int] = None
    database: str
    user: str = ""
    password: str = ""
    description: str = ""


class LLMConfig(BaseModel):
    # NOTE: intentionally no api_key field here. The key is a server-side
    # secret (see .env) and must never be accepted from a client request.
    provider: str = "openai"  # xai | ollama | openai
    base_url: str = "https://api.groq.com/openai/v1"
    model: str = "openai/gpt-oss-20b"


class QueryRequest(BaseModel):
    db_name: str
    question: str
    extra_instructions: str = ""
    limit: int = 500
    execute: bool = True  # if False, only generate SQL


class SQLExecuteRequest(BaseModel):
    db_name: str
    sql: str
    limit: int = 500


# ---------------------------------------------------------------------------
# JSON-safety helpers
# ---------------------------------------------------------------------------
# SQL NULLs become NaN/NaT in pandas, and Python's strict JSON encoder
# (used by FastAPI's default JSONResponse) rejects NaN/Infinity outright,
# crashing the whole endpoint with a 500. This converts DataFrame rows into
# plain JSON-safe values (NaN/NaT -> null, numpy scalars -> native types,
# timestamps -> ISO strings, bytes -> text) before they're returned.
def _json_safe_value(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, (list, dict)):
        return v
    if isinstance(v, str):
        return v
    # Catch NaN / NaT / pandas-NA before any type-specific formatting below,
    # so a missing timestamp (NaT) doesn't get str()'d into the text "NaT".
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        f = float(v)
        return None if (math.isnan(f) or math.isinf(f)) else f
    if isinstance(v, np.bool_):
        return bool(v)
    if isinstance(v, bool):
        return v
    if isinstance(v, float):
        return None if (math.isnan(v) or math.isinf(v)) else v
    if isinstance(v, (pd.Timestamp, datetime, date)):
        try:
            return v.isoformat()
        except Exception:
            return str(v)
    if isinstance(v, (bytes, bytearray)):
        try:
            return v.decode("utf-8")
        except Exception:
            return v.hex()
    if isinstance(v, Decimal):
        return float(v)
    return v


def df_to_json_safe_records(df: pd.DataFrame) -> List[Dict[str, Any]]:
    return [
        {k: _json_safe_value(v) for k, v in row.items()}
        for row in df.to_dict(orient="records")
    ]


# ---------------------------------------------------------------------------
# Health & Info
# ---------------------------------------------------------------------------
@app.get("/api/health")
def health():
    return {"status": "ok", "time": datetime.utcnow().isoformat()}


@app.get("/api/info")
def info():
    return {
        "product": "AI Database Query Assistant",
        "version": "1.0.0",
        "backends": list(DIALECT_CONFIG.keys()),
        "docs": "/docs",
    }


# ---------------------------------------------------------------------------
# LLM Config
# ---------------------------------------------------------------------------
@app.post("/api/llm/config")
def set_llm_config(cfg: LLMConfig):
    """Allows changing provider/base_url/model at runtime (useful for
    switching to local Ollama, etc.) but the API key always comes from the
    server's own environment (.env) — a client can never set or read it."""
    global llm_client
    llm_client = LLMClient(
        provider=cfg.provider,
        base_url=cfg.base_url,
        model=cfg.model,
        api_key=LLM_API_KEY,
    )
    ok, msg = llm_client.is_available()
    return {"success": ok, "message": msg, "config": cfg.dict()}


@app.get("/api/llm/status")
def llm_status():
    ok, msg = llm_client.is_available()
    key = llm_client.api_key
    return {
        "available": ok,
        "message": msg,
        "provider": llm_client.provider,
        "model": llm_client.model,
        "base_url": llm_client.base_url,
        "api_key_configured": bool(key),
        "api_key_length": len(key),
    }


# ---------------------------------------------------------------------------
# Database Connections
# ---------------------------------------------------------------------------
@app.get("/api/connections")
def list_connections():
    names = db_manager.get_connection_names()
    result = []
    for n in names:
        meta = db_manager.connections_meta.get(n, {})
        summary = db_manager.get_schema_summary(n)
        result.append({
            "name": n,
            "dialect": meta.get("dialect"),
            "host": meta.get("host"),
            "database": meta.get("database"),
            "description": meta.get("description"),
            "table_count": summary.get("table_count", 0),
            "scanned_at": summary.get("scanned_at"),
        })
    return {"connections": result}


@app.post("/api/connections")
def add_connection(body: ConnectionCreate):
    ok, msg = db_manager.add_connection(
        name=body.name,
        dialect=body.dialect,
        host=body.host,
        port=body.port,
        database=body.database,
        user=body.user,
        password=body.password,
        description=body.description,
        test_only=False,
    )
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"success": True, "message": msg}


@app.post("/api/connections/test")
def test_connection(body: ConnectionCreate):
    ok, msg = db_manager.add_connection(
        name=body.name or "test",
        dialect=body.dialect,
        host=body.host,
        port=body.port,
        database=body.database,
        user=body.user,
        password=body.password,
        test_only=True,
    )
    return {"success": ok, "message": msg}


@app.delete("/api/connections/{name}")
def delete_connection(name: str):
    db_manager.remove_connection(name)
    return {"success": True, "message": f"Removed {name}"}


@app.post("/api/connections/{name}/refresh-schema")
def refresh_schema(name: str):
    if name not in db_manager.get_connection_names():
        raise HTTPException(404, "Connection not found")
    schema = db_manager.scan_schema(name, force=True)
    return {
        "success": True,
        "table_count": len(schema.get("tables", {})),
        "scanned_at": schema.get("scanned_at"),
    }


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
@app.get("/api/schema/{name}")
def get_schema(name: str):
    if name not in db_manager.get_connection_names():
        raise HTTPException(404, "Connection not found")
    schema = db_manager.schemas.get(name) or db_manager.scan_schema(name)
    return schema


@app.get("/api/schema/{name}/text")
def get_schema_text(name: str):
    if name not in db_manager.get_connection_names():
        raise HTTPException(404, "Connection not found")
    return {"text": db_manager.get_schema_text(name)}


# ---------------------------------------------------------------------------
# Query (Natural Language → SQL)
# ---------------------------------------------------------------------------
@app.post("/api/query")
def run_query(body: QueryRequest):
    if body.db_name not in db_manager.get_connection_names():
        raise HTTPException(404, f"Database '{body.db_name}' not connected")

    meta = db_manager.connections_meta.get(body.db_name, {})
    dialect = meta.get("dialect", "sqlite")
    schema_text = db_manager.get_schema_text(body.db_name)

    # Generate SQL
    ok, sql_or_err, raw = llm_client.generate_sql(
        question=body.question,
        schema_text=schema_text,
        dialect=dialect,
        extra_instructions=body.extra_instructions,
    )
    if not ok:
        raise HTTPException(status_code=400, detail=sql_or_err)

    result = {
        "success": True,
        "question": body.question,
        "sql": sql_or_err,
        "raw_llm": raw,
        "rows": None,
        "columns": None,
        "row_count": 0,
        "message": "SQL generated",
    }

    if body.execute:
        success, df, msg = db_manager.execute_query(
            body.db_name, sql_or_err, limit=body.limit
        )
        if not success:
            raise HTTPException(status_code=400, detail=msg)
        result["rows"] = df_to_json_safe_records(df)
        result["columns"] = list(df.columns)
        result["row_count"] = len(df)
        result["message"] = msg

    return result


@app.post("/api/execute")
def execute_sql(body: SQLExecuteRequest):
    if body.db_name not in db_manager.get_connection_names():
        raise HTTPException(404, "Database not connected")

    success, df, msg = db_manager.execute_query(
        body.db_name, body.sql, limit=body.limit
    )
    if not success:
        raise HTTPException(status_code=400, detail=msg)

    return {
        "success": True,
        "sql": body.sql,
        "rows": df_to_json_safe_records(df),
        "columns": list(df.columns),
        "row_count": len(df),
        "message": msg,
    }


# ---------------------------------------------------------------------------
# Download helpers
# ---------------------------------------------------------------------------
@app.post("/api/download/csv")
def download_csv(body: SQLExecuteRequest):
    success, df, msg = db_manager.execute_query(body.db_name, body.sql, limit=body.limit)
    if not success:
        raise HTTPException(400, msg)

    stream = io.StringIO()
    df.to_csv(stream, index=False)
    stream.seek(0)
    return StreamingResponse(
        iter([stream.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=query_result.csv"},
    )


# ---------------------------------------------------------------------------
# Serve Frontend
# ---------------------------------------------------------------------------
FRONTEND_DIR = ROOT.parent / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
