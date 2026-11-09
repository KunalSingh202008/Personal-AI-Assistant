import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import database
from connectors.csv_connector import CSVDatasetConnector
from connectors.registry import ConnectorRegistry
from connectors.sqlite_connector import SQLiteConnector
from database import initialize_database


class ConnectorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.db_path = Path(cls.temp_dir.name) / "test_connectors.db"
        cls.db_patch = patch.object(database, "DATABASE_PATH", cls.db_path)
        cls.db_patch.start()
        initialize_database()

    @classmethod
    def tearDownClass(cls):
        cls.db_patch.stop()
        cls.temp_dir.cleanup()

    def test_sqlite_connector_read_only_and_schema(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "test_data.db"
            with closing(sqlite3.connect(db_path)) as conn:
                conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, password TEXT)")
                conn.execute("INSERT INTO users (username, password) VALUES ('kunal', 'secret_hash_123')")
                conn.commit()

            connector = SQLiteConnector("test_db", "Test Database", {"db_path": str(db_path)})

            # Test connection
            conn_test = connector.test_connection()
            self.assertTrue(conn_test["success"])

            # Inspect schema
            schema = connector.inspect_schema()
            self.assertEqual(schema["table_count"], 1)
            self.assertEqual(schema["tables"][0]["name"], "users")
            self.assertEqual(schema["tables"][0]["row_count"], 1)

            # Safe SELECT query
            query_res = connector.execute_query("SELECT id, username, password FROM users")
            self.assertEqual(query_res["columns"], ["id", "username", "password"])
            self.assertEqual(query_res["row_count"], 1)
            # Sensitive column should be redacted
            self.assertEqual(query_res["rows"][0][1], "kunal")
            self.assertEqual(query_res["rows"][0][2], "[REDACTED]")

            # Mutation queries must be blocked
            with self.assertRaises(ValueError):
                connector.execute_query("INSERT INTO users (username) VALUES ('hacker')")

            with self.assertRaises(ValueError):
                connector.execute_query("DROP TABLE users")

            with self.assertRaises(ValueError):
                connector.execute_query("SELECT 1; DROP TABLE users")

    def test_csv_connector_and_search(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            csv_path = Path(tmp_dir) / "inventory.csv"
            csv_path.write_text("item,qty,price\nLaptop,10,1200\nMouse,50,25\nKeyboard,30,75\n", encoding="utf-8")

            connector = CSVDatasetConnector("csv_inv", "Inventory", {"path": str(csv_path)})
            conn_test = connector.test_connection()
            self.assertTrue(conn_test["success"])

            schema = connector.inspect_schema()
            self.assertEqual(schema["table_count"], 1)

            query_res = connector.execute_query("Mouse")
            self.assertEqual(len(query_res["rows"]), 1)
            self.assertIn("Mouse", query_res["rows"][0])

    def test_connector_registry(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "registry_test.db"
            with closing(sqlite3.connect(db_path)) as conn:
                conn.execute("CREATE TABLE t (id INT)")
                conn.commit()

            conn = ConnectorRegistry.register(
                connector_id="custom_reg_1",
                name="Custom SQLite",
                connector_type="sqlite",
                config={"db_path": str(db_path)},
                is_read_only=True,
            )
            self.assertEqual(conn.id, "custom_reg_1")

            fetched = ConnectorRegistry.get("custom_reg_1")
            self.assertIsNotNone(fetched)
            self.assertEqual(fetched.name, "Custom SQLite")

            all_conns = ConnectorRegistry.list_all()
            ids = [c["id"] for c in all_conns]
            self.assertIn("custom_reg_1", ids)
            self.assertIn("primary_sqlite", ids)

            removed = ConnectorRegistry.remove("custom_reg_1")
            self.assertTrue(removed)


if __name__ == "__main__":
    unittest.main()
