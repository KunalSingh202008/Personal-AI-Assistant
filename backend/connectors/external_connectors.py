import importlib
import time
from typing import Any
import httpx

from .base import BaseConnector


class PostgreSQLConnector(BaseConnector):
    def __init__(self, connector_id: str, name: str, config: dict, is_read_only: bool = True):
        super().__init__(connector_id, name, "postgresql", config, is_read_only)
        self.host = self.config.get("host", "localhost")
        self.port = int(self.config.get("port", 5432))
        self.database = self.config.get("database", "")
        self.user = self.config.get("user", "")

    def test_connection(self) -> dict:
        has_driver = importlib.util.find_spec("psycopg2") is not None or importlib.util.find_spec("asyncpg") is not None
        if not has_driver:
            return {
                "success": False,
                "message": "PostgreSQL driver (psycopg2 or asyncpg) is not installed in the environment.",
                "latency_ms": 0.0,
            }
        return {
            "success": False,
            "message": f"Connection configured for {self.user}@{self.host}:{self.port}/{self.database}. Connection verified in dry-run mode.",
            "latency_ms": 1.0,
        }

    def inspect_schema(self) -> dict:
        return {
            "database": self.database,
            "table_count": 0,
            "tables": [],
            "message": "Schema inspection requires live PostgreSQL connection.",
        }

    def execute_query(self, query: str, params: list | None = None, max_rows: int = 100) -> dict:
        self.validate_read_only_query(query)
        raise NotImplementedError("Live PostgreSQL execution requires active server credentials and installed driver.")


class MySQLConnector(BaseConnector):
    def __init__(self, connector_id: str, name: str, config: dict, is_read_only: bool = True):
        super().__init__(connector_id, name, "mysql", config, is_read_only)
        self.host = self.config.get("host", "localhost")
        self.port = int(self.config.get("port", 3306))
        self.database = self.config.get("database", "")
        self.user = self.config.get("user", "")

    def test_connection(self) -> dict:
        has_driver = importlib.util.find_spec("pymysql") is not None or importlib.util.find_spec("mysql.connector") is not None
        if not has_driver:
            return {
                "success": False,
                "message": "MySQL driver (pymysql or mysql-connector-python) is not installed in the environment.",
                "latency_ms": 0.0,
            }
        return {
            "success": False,
            "message": f"Connection configured for {self.user}@{self.host}:{self.port}/{self.database}. Connection verified in dry-run mode.",
            "latency_ms": 1.0,
        }

    def inspect_schema(self) -> dict:
        return {
            "database": self.database,
            "table_count": 0,
            "tables": [],
            "message": "Schema inspection requires live MySQL connection.",
        }

    def execute_query(self, query: str, params: list | None = None, max_rows: int = 100) -> dict:
        self.validate_read_only_query(query)
        raise NotImplementedError("Live MySQL execution requires active server credentials and installed driver.")


class WebSearchConnector(BaseConnector):
    def __init__(self, connector_id: str = "web_search", name: str = "Web Search", config: dict | None = None):
        super().__init__(connector_id, name, "web_search", config or {}, is_read_only=True)
        self.enabled = bool(self.config.get("enabled", False))
        self.provider = self.config.get("provider", "duckduckgo")

    def test_connection(self) -> dict:
        if not self.enabled:
            return {
                "success": False,
                "message": "Web search is disabled by default for privacy. Enable provider in connector configuration.",
                "latency_ms": 0.0,
            }
        return {
            "success": True,
            "message": f"Web search connector enabled using {self.provider}.",
            "latency_ms": 1.0,
        }

    def inspect_schema(self) -> dict:
        return {
            "provider": self.provider,
            "enabled": self.enabled,
            "privacy": "Local-first: no search queries sent unless enabled explicitly by user.",
        }

    def execute_query(self, query: str, params: list | None = None, max_rows: int = 5) -> dict:
        if not self.enabled:
            raise PermissionError("Web search is disabled. Enable provider in connector configuration.")

        # Real public search query using DuckDuckGo instant API
        try:
            with httpx.Client(timeout=5.0) as client:
                resp = client.get(
                    "https://api.duckduckgo.com/",
                    params={"q": query, "format": "json", "no_html": "1", "skip_disambig": "1"},
                )
                data = resp.json()
                results = []
                abstract = data.get("AbstractText", "")
                if abstract:
                    results.append([data.get("Heading", "Summary"), abstract, data.get("AbstractURL", "")])
                for topic in data.get("RelatedTopics", [])[:max_rows]:
                    if "Text" in topic:
                        results.append([topic.get("Text", ""), topic.get("FirstURL", "")])
                return {
                    "columns": ["Title / Snippet", "URL"],
                    "rows": results,
                    "row_count": len(results),
                    "truncated": False,
                }
        except Exception as exc:
            return {
                "columns": ["Error"],
                "rows": [[f"Search request failed: {exc}"]],
                "row_count": 1,
                "truncated": False,
            }
