import re
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from typing import Any

from .base import BaseConnector

SENSITIVE_COLUMN_PATTERN = re.compile(r"(password|secret|token|api_key|private_key|salt|hash)", re.IGNORECASE)


class SQLiteConnector(BaseConnector):
    def __init__(self, connector_id: str, name: str, config: dict, is_read_only: bool = True):
        super().__init__(connector_id, name, "sqlite", config, is_read_only)
        self.db_path = Path(self.config.get("db_path", "")).resolve()

    def _get_ro_connection(self) -> sqlite3.Connection:
        if not self.db_path.is_file():
            raise FileNotFoundError(f"SQLite database file not found: {self.db_path}")
        # Open in URI read-only mode
        uri = f"file:{self.db_path.as_posix()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    def test_connection(self) -> dict:
        start = time.perf_counter()
        try:
            with closing(self._get_ro_connection()) as conn:
                conn.execute("SELECT 1").fetchone()
            latency = round((time.perf_counter() - start) * 1000, 2)
            return {
                "success": True,
                "message": f"Successfully connected to SQLite database at {self.db_path.name}",
                "latency_ms": latency,
            }
        except Exception as exc:
            return {
                "success": False,
                "message": f"Failed to open database: {exc}",
                "latency_ms": round((time.perf_counter() - start) * 1000, 2),
            }

    def inspect_schema(self) -> dict:
        with closing(self._get_ro_connection()) as conn:
            table_rows = conn.execute(
                """
                SELECT name, type FROM sqlite_master
                WHERE type IN ('table', 'view') AND name NOT LIKE 'sqlite_%'
                ORDER BY name
                """
            ).fetchall()

            tables = []
            for row in table_rows:
                table_name = row["name"]
                col_rows = conn.execute(f"PRAGMA table_info('{table_name}')").fetchall()
                columns = [
                    {
                        "name": col["name"],
                        "type": col["type"] or "TEXT",
                        "notnull": bool(col["notnull"]),
                        "pk": bool(col["pk"]),
                    }
                    for col in col_rows
                ]
                try:
                    count_row = conn.execute(f"SELECT COUNT(*) FROM '{table_name}'").fetchone()
                    count = count_row[0] if count_row else 0
                except Exception:
                    count = 0

                tables.append({
                    "name": table_name,
                    "type": row["type"],
                    "columns": columns,
                    "row_count": count,
                })

            return {
                "database": self.db_path.name,
                "path": str(self.db_path),
                "table_count": len(tables),
                "tables": tables,
            }

    def execute_query(self, query: str, params: list | None = None, max_rows: int = 100) -> dict:
        self.validate_read_only_query(query)
        params = params or []

        with closing(self._get_ro_connection()) as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            desc = cursor.description
            if not desc:
                return {"columns": [], "rows": [], "row_count": 0, "truncated": False}

            columns = [d[0] for d in desc]
            fetched = cursor.fetchmany(max_rows + 1)
            truncated = len(fetched) > max_rows
            rows = fetched[:max_rows]

            # Redact sensitive columns
            sanitized_rows = []
            for row in rows:
                sanitized_row = []
                for idx, val in enumerate(row):
                    col_name = columns[idx]
                    if SENSITIVE_COLUMN_PATTERN.search(col_name) and val is not None:
                        sanitized_row.append("[REDACTED]")
                    else:
                        sanitized_row.append(val)
                sanitized_rows.append(sanitized_row)

            return {
                "columns": columns,
                "rows": sanitized_rows,
                "row_count": len(sanitized_rows),
                "truncated": truncated,
            }
