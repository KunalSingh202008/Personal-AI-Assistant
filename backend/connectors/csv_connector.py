import csv
import io
import time
from pathlib import Path
from typing import Any

from .base import BaseConnector


def _detect_type(val: str) -> str:
    clean = val.strip()
    if not clean:
        return "NULL"
    if clean.isdigit() or (clean.startswith("-") and clean[1:].isdigit()):
        return "INTEGER"
    try:
        float(clean)
        return "REAL"
    except ValueError:
        return "TEXT"


class CSVDatasetConnector(BaseConnector):
    def __init__(self, connector_id: str, name: str, config: dict, is_read_only: bool = True):
        super().__init__(connector_id, name, "csv", config, is_read_only)
        self.path = Path(self.config.get("path", "")).resolve()

    def _get_csv_files(self) -> list[Path]:
        if self.path.is_file() and self.path.suffix.lower() == ".csv":
            return [self.path]
        if self.path.is_dir():
            return sorted(self.path.glob("*.csv"))
        return []

    def test_connection(self) -> dict:
        start = time.perf_counter()
        files = self._get_csv_files()
        latency = round((time.perf_counter() - start) * 1000, 2)
        if not files:
            return {
                "success": False,
                "message": f"No valid CSV files found at path: {self.path}",
                "latency_ms": latency,
            }
        return {
            "success": True,
            "message": f"Found {len(files)} CSV file(s) at {self.path.name}",
            "latency_ms": latency,
        }

    def inspect_schema(self) -> dict:
        files = self._get_csv_files()
        tables = []
        for file in files:
            try:
                with open(file, "r", encoding="utf-8", errors="ignore") as f:
                    reader = csv.reader(f)
                    headers = next(reader, [])
                    sample_rows = []
                    total_rows = 0
                    for row in reader:
                        total_rows += 1
                        if len(sample_rows) < 5:
                            sample_rows.append(row)

                columns = []
                for i, h in enumerate(headers):
                    col_type = "TEXT"
                    if sample_rows:
                        types = [_detect_type(r[i]) for r in sample_rows if i < len(r)]
                        if types:
                            col_type = max(set(types), key=types.count)
                    columns.append({"name": h, "type": col_type})

                tables.append({
                    "name": file.stem,
                    "file_path": str(file),
                    "columns": columns,
                    "row_count": total_rows,
                })
            except Exception:
                continue

        return {
            "dataset_path": str(self.path),
            "table_count": len(tables),
            "tables": tables,
        }

    def execute_query(self, query: str, params: list | None = None, max_rows: int = 100) -> dict:
        """
        Executes a search or filter over the CSV data.
        Query format: plain text search term or 'TABLE_NAME: keyword'
        """
        files = self._get_csv_files()
        if not files:
            return {"columns": [], "rows": [], "row_count": 0, "truncated": False}

        target_file = files[0]
        search_term = query.strip()
        if ":" in search_term:
            t_name, _, rest = search_term.partition(":")
            matching = [f for f in files if f.stem.lower() == t_name.strip().lower()]
            if matching:
                target_file = matching[0]
                search_term = rest.strip()

        with open(target_file, "r", encoding="utf-8", errors="ignore") as f:
            reader = csv.reader(f)
            headers = next(reader, [])
            matching_rows = []
            for row in reader:
                if not search_term or any(search_term.lower() in str(cell).lower() for cell in row):
                    matching_rows.append(row)
                    if len(matching_rows) >= max_rows + 1:
                        break

        truncated = len(matching_rows) > max_rows
        return {
            "columns": headers,
            "rows": matching_rows[:max_rows],
            "row_count": len(matching_rows[:max_rows]),
            "truncated": truncated,
        }
