"""
AI Database Query Assistant - FastAPI Backend
Proper REST API product for natural language → SQL
"""

from __future__ import annotations

import io
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# Make utils importable
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from utils.db_manager import DatabaseManager, DIALECT_CONFIG
from utils.llm_client import LLMClient, DEFAULT_XAI_URL, DEFAULT_MODEL_XAI

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

# Default LLM – load from Railway / environment variables if set
llm_client = LLMClient(
    provider=os.getenv("LLM_PROVIDER", "openai"),
    base_url=os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1"),
    model=os.getenv("LLM_MODEL", "openai/gpt-oss-20b"),
    api_key=os.getenv("LLM_API_KEY", ""),
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
    provider: str = "openai"  # xai | ollama | openai
    base_url: str = "https://api.groq.com/openai/v1"
    model: str = "openai/gpt-oss-20b"
    api_key: str = ""


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
    global llm_client
    llm_client = LLMClient(
        provider=cfg.provider,
        base_url=cfg.base_url,
        model=cfg.model,
        api_key=cfg.api_key,
    )
    ok, msg = llm_client.is_available()
    return {"success": ok, "message": msg, "config": cfg.dict(exclude={"api_key"})}


@app.get("/api/llm/status")
def llm_status():
    ok, msg = llm_client.is_available()
    return {
        "available": ok,
        "message": msg,
        "provider": llm_client.provider,
        "model": llm_client.model,
        "base_url": llm_client.base_url,
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
        # User-friendly message for schema / generation failures
        detail = sql_or_err or "Could not complete this request."
        if detail.startswith("-- ERROR"):
            detail = detail.replace("-- ERROR:", "").strip() or "Could not find this information in the selected database schema."
        if "cannot answer" in detail.lower() or "available schema" in detail.lower():
            detail = "Could not find this information in the selected database schema. Please try a different question."
        raise HTTPException(status_code=400, detail=detail)

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
        result["rows"] = df.to_dict(orient="records")
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
        "rows": df.to_dict(orient="records"),
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
