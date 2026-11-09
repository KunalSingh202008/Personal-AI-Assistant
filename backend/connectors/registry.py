from pathlib import Path
from typing import Any

from database import (
    delete_database_connector,
    get_database_connector,
    list_database_connectors,
    save_database_connector,
)
from .base import BaseConnector
from .csv_connector import CSVDatasetConnector
from .external_connectors import MySQLConnector, PostgreSQLConnector, WebSearchConnector
from .sqlite_connector import SQLiteConnector

DEFAULT_DB_PATH = Path(__file__).resolve().parents[1] / "nexus_ai.db"


class ConnectorRegistry:
    @staticmethod
    def _create_instance(item: dict) -> BaseConnector:
        c_type = item["connector_type"].lower()
        c_id = item["id"]
        c_name = item["name"]
        config = item.get("config", {})
        is_ro = item.get("is_read_only", True)

        if c_type == "sqlite":
            return SQLiteConnector(c_id, c_name, config, is_ro)
        elif c_type == "csv":
            return CSVDatasetConnector(c_id, c_name, config, is_ro)
        elif c_type == "postgresql":
            return PostgreSQLConnector(c_id, c_name, config, is_ro)
        elif c_type == "mysql":
            return MySQLConnector(c_id, c_name, config, is_ro)
        elif c_type == "web_search":
            return WebSearchConnector(c_id, c_name, config)
        else:
            raise ValueError(f"Unknown connector type: {c_type}")

    @classmethod
    def get(cls, connector_id: str) -> BaseConnector | None:
        # Check built-in primary sqlite
        if connector_id == "primary_sqlite":
            return SQLiteConnector("primary_sqlite", "Nexus AI Internal SQLite", {"db_path": str(DEFAULT_DB_PATH)}, is_read_only=True)
        if connector_id == "web_search":
            item = get_database_connector("web_search")
            config = item["config"] if item else {"enabled": False}
            return WebSearchConnector("web_search", "Web Search", config)

        item = get_database_connector(connector_id)
        if not item:
            return None
        return cls._create_instance(item)

    @classmethod
    def list_all(cls) -> list[dict]:
        connectors = [
            {
                "id": "primary_sqlite",
                "name": "Nexus AI Internal SQLite",
                "connector_type": "sqlite",
                "config": {"db_path": str(DEFAULT_DB_PATH)},
                "is_read_only": True,
            }
        ]
        db_items = list_database_connectors()
        connectors.extend(db_items)
        return connectors

    @classmethod
    def register(
        cls,
        connector_id: str,
        name: str,
        connector_type: str,
        config: dict,
        is_read_only: bool = True,
    ) -> BaseConnector:
        item = save_database_connector(connector_id, name, connector_type, config, is_read_only)
        return cls._create_instance(item)

    @classmethod
    def remove(cls, connector_id: str) -> bool:
        if connector_id == "primary_sqlite":
            raise ValueError("Cannot delete built-in primary database connector.")
        return delete_database_connector(connector_id)
