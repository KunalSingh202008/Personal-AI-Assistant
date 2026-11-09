from abc import ABC, abstractmethod
import re
from typing import Any

DISALLOWED_SQL_PATTERNS = [
    r"\binsert\b",
    r"\bupdate\b",
    r"\bdelete\b",
    r"\bdrop\b",
    r"\balter\b",
    r"\bcreate\b",
    r"\btruncate\b",
    r"\battach\b",
    r"\bdetach\b",
    r"\bvacuum\b",
    r"\bgrant\b",
    r"\brevoke\b",
    r"\bexec\b",
    r"\bexecute\b",
]


class BaseConnector(ABC):
    def __init__(self, connector_id: str, name: str, connector_type: str, config: dict, is_read_only: bool = True):
        self.id = connector_id
        self.name = name
        self.connector_type = connector_type
        self.config = config
        self.is_read_only = is_read_only

    @abstractmethod
    def test_connection(self) -> dict:
        """Test connectivity and credentials. Returns {success, message, latency_ms}."""
        pass

    @abstractmethod
    def inspect_schema(self) -> dict:
        """Introspect tables, columns, data types, and row count estimates."""
        pass

    @abstractmethod
    def execute_query(self, query: str, params: list | None = None, max_rows: int = 100) -> dict:
        """Execute a read-only query and return columns, rows, and summary."""
        pass

    def validate_read_only_query(self, query: str) -> None:
        """Validate that the query contains only safe read-only statements."""
        clean_query = query.strip()
        if not clean_query:
            raise ValueError("Query string cannot be empty.")

        # Disallow semicolon-separated multiple statements
        statements = [s for s in clean_query.split(";") if s.strip()]
        if len(statements) > 1:
            raise ValueError("Multiple statements separated by semicolon are disallowed.")

        lowered = clean_query.lower()

        # Must start with SELECT or EXPLAIN or safe PRAGMA
        allowed_starts = ("select", "explain", "with", "pragma table_info", "pragma index_list")
        if not any(lowered.startswith(prefix) for prefix in allowed_starts):
            raise ValueError("Only read-only SELECT, EXPLAIN, and WITH queries are allowed.")

        # Scan for disallowed mutation keywords
        for pattern in DISALLOWED_SQL_PATTERNS:
            if re.search(pattern, lowered):
                raise ValueError(f"Mutation keyword matched by pattern '{pattern}' is not permitted.")

    def close(self) -> None:
        pass
