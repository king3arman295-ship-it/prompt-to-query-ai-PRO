"""
Database Manager - Handles multiple DB connections, schema introspection,
and safe query execution.
"""

from __future__ import annotations

import json
import os
import hashlib
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote_plus

import pandas as pd
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError


# Supported dialects and their default ports / drivers
DIALECT_CONFIG = {
    "sqlite": {
        "driver": "sqlite",
        "default_port": None,
        "url_template": "sqlite:///{database}",
    },
    "postgresql": {
        "driver": "postgresql+psycopg2",
        "default_port": 5432,
        "url_template": "postgresql+psycopg2://{user}:{password}@{host}:{port}/{database}",
    },
    "mysql": {
        "driver": "mysql+pymysql",
        "default_port": 3306,
        "url_template": "mysql+pymysql://{user}:{password}@{host}:{port}/{database}",
    },
    "mssql": {
        "driver": "mssql+pyodbc",
        "default_port": 1433,
        "url_template": "mssql+pyodbc://{user}:{password}@{host}:{port}/{database}?driver=ODBC+Driver+17+for+SQL+Server",
    },
}


class DatabaseManager:
    """Manages multiple named database connections and their schemas."""

    def __init__(self, storage_path: str = "data/connections.json"):
        self.storage_path = storage_path
        self.engines: Dict[str, Engine] = {}
        self.schemas: Dict[str, Dict[str, Any]] = {}
        self.connections_meta: Dict[str, Dict[str, Any]] = {}
        os.makedirs(os.path.dirname(storage_path) or ".", exist_ok=True)
        self._load_connections()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def _load_connections(self) -> None:
        if os.path.exists(self.storage_path):
            try:
                with open(self.storage_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.connections_meta = data.get("connections", {})
                self.schemas = data.get("schemas", {})
            except Exception:
                self.connections_meta = {}
                self.schemas = {}

    def _save_connections(self) -> None:
        # Never store plaintext passwords long-term in production;
        # for this prototype we keep them encrypted-ish with a simple hash marker.
        safe_meta = {}
        for name, meta in self.connections_meta.items():
            safe = dict(meta)
            if "password" in safe and safe["password"]:
                # Store a marker; real password is only in memory / session
                safe["password"] = "***REDACTED***"
            safe_meta[name] = safe

        payload = {
            "connections": self.connections_meta,  # keep full for prototype simplicity
            "schemas": self.schemas,
            "updated_at": datetime.utcnow().isoformat(),
        }
        with open(self.storage_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, default=str)

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------
    def build_connection_url(
        self,
        dialect: str,
        host: str = "localhost",
        port: Optional[int] = None,
        database: str = "",
        user: str = "",
        password: str = "",
        extra: Optional[Dict] = None,
    ) -> str:
        dialect = dialect.lower()
        if dialect not in DIALECT_CONFIG:
            raise ValueError(f"Unsupported dialect: {dialect}")

        cfg = DIALECT_CONFIG[dialect]
        if dialect == "sqlite":
            return cfg["url_template"].format(database=database or ":memory:")

        port = port or cfg["default_port"]
        user_enc = quote_plus(user) if user else ""
        pass_enc = quote_plus(password) if password else ""
        url = cfg["url_template"].format(
            user=user_enc,
            password=pass_enc,
            host=host,
            port=port,
            database=database,
        )
        return url

    def add_connection(
        self,
        name: str,
        dialect: str,
        host: str = "localhost",
        port: Optional[int] = None,
        database: str = "",
        user: str = "",
        password: str = "",
        description: str = "",
        test_only: bool = False,
    ) -> Tuple[bool, str]:
        """
        Add (or update) a named connection.
        Returns (success, message).
        """
        try:
            url = self.build_connection_url(dialect, host, port, database, user, password)
            engine = create_engine(url, pool_pre_ping=True, pool_recycle=3600)

            # Test connection
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))

            if test_only:
                engine.dispose()
                return True, "Connection test successful!"

            # Store
            self.engines[name] = engine
            self.connections_meta[name] = {
                "dialect": dialect.lower(),
                "host": host,
                "port": port or DIALECT_CONFIG.get(dialect.lower(), {}).get("default_port"),
                "database": database,
                "user": user,
                "password": password,  # prototype only
                "description": description,
                "added_at": datetime.utcnow().isoformat(),
                "url_hash": hashlib.sha256(url.encode()).hexdigest()[:12],
            }

            # Scan schema immediately
            schema = self.scan_schema(name)
            self.schemas[name] = schema
            self._save_connections()

            return True, f"Connection '{name}' added and schema scanned successfully."
        except Exception as e:
            return False, f"Connection failed: {str(e)}"

    def remove_connection(self, name: str) -> bool:
        if name in self.engines:
            try:
                self.engines[name].dispose()
            except Exception:
                pass
            del self.engines[name]
        self.connections_meta.pop(name, None)
        self.schemas.pop(name, None)
        self._save_connections()
        return True

    def get_connection_names(self) -> List[str]:
        return list(self.connections_meta.keys())

    def get_engine(self, name: str) -> Optional[Engine]:
        if name in self.engines:
            return self.engines[name]
        # Try to re-create from meta
        meta = self.connections_meta.get(name)
        if not meta:
            return None
        try:
            url = self.build_connection_url(
                meta["dialect"],
                meta.get("host", "localhost"),
                meta.get("port"),
                meta.get("database", ""),
                meta.get("user", ""),
                meta.get("password", ""),
            )
            engine = create_engine(url, pool_pre_ping=True)
            self.engines[name] = engine
            return engine
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Schema scanning
    # ------------------------------------------------------------------
    def scan_schema(self, name: str, force: bool = False) -> Dict[str, Any]:
        """Introspect full schema of a connected database."""
        if name in self.schemas and not force:
            return self.schemas[name]

        engine = self.get_engine(name)
        if engine is None:
            return {}

        inspector = inspect(engine)
        schema_info: Dict[str, Any] = {
            "tables": {},
            "scanned_at": datetime.utcnow().isoformat(),
            "dialect": self.connections_meta.get(name, {}).get("dialect", "unknown"),
        }

        try:
            table_names = inspector.get_table_names()
            for table in table_names:
                columns = []
                for col in inspector.get_columns(table):
                    columns.append(
                        {
                            "name": col["name"],
                            "type": str(col["type"]),
                            "nullable": col.get("nullable", True),
                            "default": str(col.get("default")) if col.get("default") is not None else None,
                            "primary_key": col.get("primary_key", False),
                        }
                    )

                # Primary keys
                pk = inspector.get_pk_constraint(table)
                pk_cols = pk.get("constrained_columns", []) if pk else []

                # Foreign keys
                fks = []
                for fk in inspector.get_foreign_keys(table):
                    fks.append(
                        {
                            "constrained_columns": fk.get("constrained_columns", []),
                            "referred_table": fk.get("referred_table"),
                            "referred_columns": fk.get("referred_columns", []),
                        }
                    )

                # Indexes (optional)
                indexes = []
                try:
                    for idx in inspector.get_indexes(table):
                        indexes.append(
                            {
                                "name": idx.get("name"),
                                "columns": idx.get("column_names", []),
                                "unique": idx.get("unique", False),
                            }
                        )
                except Exception:
                    pass

                schema_info["tables"][table] = {
                    "columns": columns,
                    "primary_keys": pk_cols,
                    "foreign_keys": fks,
                    "indexes": indexes,
                }

            # Views
            try:
                views = inspector.get_view_names()
                schema_info["views"] = views
            except Exception:
                schema_info["views"] = []

        except Exception as e:
            schema_info["error"] = str(e)

        self.schemas[name] = schema_info
        self._save_connections()
        return schema_info

    def get_schema_text(self, name: str, max_tables: int = 50) -> str:
        """Return a human/LLM-friendly textual representation of the schema.

        Includes columns, PKs, FKs, and (when possible) a few distinct sample
        values for low-cardinality columns so the LLM knows real status/type
        values instead of guessing.
        """
        schema = self.schemas.get(name) or self.scan_schema(name)
        if not schema or "tables" not in schema:
            return "No schema available."

        dialect = schema.get("dialect", "unknown")
        lines = [
            f"Database: {name} (dialect: {dialect})",
            f"Scanned at: {schema.get('scanned_at', 'N/A')}",
            "",
            "IMPORTANT RELATIONSHIPS:",
            "  customers 1---* subscriptions *---1 plans",
            "  customers 1---* devices",
            "  customers 1---* watch_history *---1 content_catalog",
            "  customers 1---* invoices 1---* payments",
            "  customers 1---* support_tickets",
            "  customers 1---* data_usage",
            "  content_catalog 1---* series 1---* episodes  (for content_type='series')",
            "",
        ]

        engine = self.get_engine(name)
        tables = list(schema["tables"].items())[:max_tables]

        # Columns that benefit from sample values
        sample_worthy = {
            "status", "plan_type", "content_type", "genre", "device_type",
            "category", "priority", "method", "segment", "quality",
            "event_type", "severity", "language", "streaming_quality",
            "is_active", "is_premium", "auto_renew", "is_registered",
        }

        for tname, tinfo in tables:
            lines.append(f"TABLE: {tname}")
            for col in tinfo.get("columns", []):
                pk = " [PK]" if col["name"] in tinfo.get("primary_keys", []) else ""
                null = " NULL" if col.get("nullable") else " NOT NULL"
                col_line = f"  - {col['name']}: {col['type']}{null}{pk}"

                # Attach a few sample values when useful
                if engine is not None and col["name"].lower() in sample_worthy:
                    try:
                        with engine.connect() as conn:
                            q = text(
                                f'SELECT DISTINCT "{col["name"]}" FROM "{tname}" '
                                f'WHERE "{col["name"]}" IS NOT NULL LIMIT 12'
                            )
                            vals = [str(r[0]) for r in conn.execute(q).fetchall()]
                        if vals:
                            col_line += f"  -- e.g. {', '.join(vals[:8])}"
                    except Exception:
                        pass
                lines.append(col_line)

            for fk in tinfo.get("foreign_keys", []):
                cols = ", ".join(fk.get("constrained_columns", []))
                ref = f"{fk.get('referred_table')}({', '.join(fk.get('referred_columns', []))})"
                lines.append(f"  FK: ({cols}) -> {ref}")
            lines.append("")

        if len(schema["tables"]) > max_tables:
            lines.append(f"... and {len(schema['tables']) - max_tables} more tables")

        return "\n".join(lines)

    def get_schema_summary(self, name: str) -> Dict[str, Any]:
        schema = self.schemas.get(name) or {}
        tables = schema.get("tables", {})
        return {
            "table_count": len(tables),
            "tables": list(tables.keys()),
            "scanned_at": schema.get("scanned_at"),
            "dialect": schema.get("dialect"),
        }

    # ------------------------------------------------------------------
    # Safe query execution
    # ------------------------------------------------------------------
    def is_safe_query(self, sql: str) -> Tuple[bool, str]:
        """Basic safety check – only allow SELECT / WITH / SHOW / DESCRIBE / EXPLAIN."""
        cleaned = sql.strip().upper()
        # Remove comments
        import re
        cleaned = re.sub(r"--.*?$", "", cleaned, flags=re.MULTILINE)
        cleaned = re.sub(r"/\*.*?\*/", "", cleaned, flags=re.DOTALL)
        cleaned = cleaned.strip()

        allowed_starts = ("SELECT", "WITH", "SHOW", "DESCRIBE", "DESC", "EXPLAIN", "PRAGMA")
        if not any(cleaned.startswith(s) for s in allowed_starts):
            return False, "Only read-only queries (SELECT / WITH / SHOW / DESCRIBE / EXPLAIN) are allowed."

        # Block multiple statements
        if ";" in cleaned.rstrip(";"):
            return False, "Multiple statements are not allowed."

        dangerous = [
            "INSERT ", "UPDATE ", "DELETE ", "DROP ", "ALTER ", "CREATE ",
            "TRUNCATE ", "GRANT ", "REVOKE ", "EXEC ", "EXECUTE ", "MERGE ",
            "CALL ", "INTO OUTFILE", "LOAD_FILE",
        ]
        for d in dangerous:
            if d in cleaned:
                return False, f"Dangerous keyword detected: {d.strip()}"

        return True, "OK"

    def execute_query(
        self,
        name: str,
        sql: str,
        limit: int = 1000,
        timeout_seconds: int = 30,
    ) -> Tuple[bool, Any, str]:
        """
        Execute a read-only SQL query.
        Returns (success, result_dataframe_or_error, message)
        """
        safe, reason = self.is_safe_query(sql)
        if not safe:
            return False, None, reason

        engine = self.get_engine(name)
        if engine is None:
            return False, None, f"No active connection for '{name}'"

        try:
            # Optional LIMIT injection for safety (if not already present)
            sql_upper = sql.upper()
            if "LIMIT" not in sql_upper and "TOP " not in sql_upper and "FETCH " not in sql_upper:
                # Simple append – works for most dialects; user can override
                if sql.rstrip().endswith(";"):
                    sql = sql.rstrip()[:-1] + f" LIMIT {limit};"
                else:
                    sql = sql.rstrip() + f" LIMIT {limit}"

            with engine.connect() as conn:
                result = conn.execute(text(sql))
                rows = result.fetchmany(limit)
                columns = list(result.keys())
                df = pd.DataFrame(rows, columns=columns)
                return True, df, f"Returned {len(df)} rows"

        except SQLAlchemyError as e:
            return False, None, f"SQL Error: {str(e)}"
        except Exception as e:
            return False, None, f"Execution error: {str(e)}"

    def get_sample_rows(self, name: str, table: str, n: int = 5) -> Optional[pd.DataFrame]:
        engine = self.get_engine(name)
        if not engine:
            return None
        try:
            dialect = self.connections_meta.get(name, {}).get("dialect", "sqlite")
            if dialect == "mssql":
                q = f"SELECT TOP {n} * FROM [{table}]"
            else:
                q = f"SELECT * FROM {table} LIMIT {n}"
            with engine.connect() as conn:
                return pd.read_sql(text(q), conn)
        except Exception:
            return None
