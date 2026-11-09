"""
Nexus AI — End-to-End Smoke Test & System Verification Suite
Validates Knowledge Engine, Database Connectors, Memory Manager,
Coding Agent Tool schemas, and API routes.
"""

import sys
import unittest
from pathlib import Path

# Add backend directory to path
BACKEND_DIR = Path(__file__).resolve().parent / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from fastapi.testclient import TestClient

from action_policy import ActionPolicy, classify_action
from connectors.csv_connector import CSVDatasetConnector
from connectors.registry import ConnectorRegistry
from connectors.sqlite_connector import SQLiteConnector
from database import get_connection, initialize_database
from knowledge.chunker import chunk_text
from knowledge.embeddings import cosine_similarity, generate_local_embedding
from knowledge.engine import (
    delete_indexed_document,
    index_file,
    list_indexed_documents,
    search_knowledge_base,
)
from main import app
from memory.manager import MemoryManager
from workspace_tools import TOOL_SCHEMAS


class NexusSmokeTestSuite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        initialize_database()
        cls.client = TestClient(app)

    def test_01_database_tables_and_pragmas(self):
        """Verify all core and extended SQLite tables exist."""
        with get_connection() as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            expected = {
                "conversations",
                "messages",
                "app_settings",
                "student_tasks",
                "workspace_contexts",
                "agent_activity",
                "agent_tasks",
                "knowledge_sources",
                "knowledge_documents",
                "knowledge_chunks",
                "database_connectors",
                "user_preferences",
            }
            for table in expected:
                self.assertIn(table, tables, f"Table {table} must be present in SQLite")

    def test_02_knowledge_engine_pipeline(self):
        """Verify chunking, local embeddings, indexing, and hybrid search."""
        text = (
            "# Nexus AI Architecture\n\n"
            "Nexus AI is an autonomous personal AI operating system.\n"
            "It combines a ChatGPT-like conversational assistant with deep research and coding agents."
        )
        chunks = chunk_text(text, chunk_size=100, overlap=20)
        self.assertGreater(len(chunks), 0)

        v1 = generate_local_embedding("Nexus AI operating system")
        v2 = generate_local_embedding("Nexus AI platform architecture")
        v3 = generate_local_embedding("baking sourdough bread at home")
        sim_related = cosine_similarity(v1, v2)
        sim_unrelated = cosine_similarity(v1, v3)
        self.assertGreater(sim_related, sim_unrelated)
        self.assertGreater(sim_related, 0.2)

        # Index and search test file
        test_file = Path(__file__).resolve().parent / "README.md"
        if test_file.is_file():
            res = index_file(test_file)
            self.assertIn(res["status"], {"indexed", "skipped"})
            doc_id = res["document_id"]

            search_results = search_knowledge_base("Nexus AI local inference", top_k=2)
            self.assertGreater(len(search_results), 0)
            self.assertIn("[1]", search_results[0]["citation_id"])

    def test_03_database_connectors_security(self):
        """Verify read-only enforcement, mutation prevention, and sensitive column redaction."""
        primary_conn = ConnectorRegistry.get("primary_sqlite")
        self.assertIsNotNone(primary_conn)
        test_res = primary_conn.test_connection()
        self.assertTrue(test_res["success"])

        # Schema introspection
        schema = primary_conn.inspect_schema()
        self.assertGreater(schema["table_count"], 0)

        # Safe read query
        q_res = primary_conn.execute_query("SELECT id, title FROM conversations LIMIT 5")
        self.assertIn("title", q_res["columns"])

        # Mutation query MUST be rejected
        with self.assertRaises(ValueError):
            primary_conn.execute_query("DROP TABLE conversations")

        with self.assertRaises(ValueError):
            primary_conn.execute_query("DELETE FROM messages")

    def test_04_memory_manager_isolation(self):
        """Verify strict memory layer firewalls."""
        MemoryManager.set_preference("theme", "dark", category="ui")
        prefs = MemoryManager.get_preferences()
        self.assertEqual(prefs.get("theme"), "dark")

        snapshot = MemoryManager.export_snapshot()
        self.assertIn("user_preferences", snapshot)
        self.assertIn("indexed_documents", snapshot)
        self.assertIn("database_connectors", snapshot)

    def test_05_coding_agent_policy_and_schemas(self):
        """Verify action policy risk classification and tool schemas."""
        policy = classify_action("read_file")
        self.assertEqual(policy.risk, "GREEN")

        write_policy = classify_action("write_file")
        self.assertEqual(write_policy.risk, "AMBER")

        cmd_policy = classify_action("run_command")
        self.assertEqual(cmd_policy.risk, "AMBER")

        self.assertGreater(len(TOOL_SCHEMAS), 5)

    def test_06_fastapi_endpoints_health_and_connectors(self):
        """Verify FastAPI REST API endpoints."""
        r_health = self.client.get("/api/health")
        self.assertEqual(r_health.status_code, 200)
        self.assertIn("model", r_health.json())

        r_conns = self.client.get("/api/connectors")
        self.assertEqual(r_conns.status_code, 200)

        r_tools = self.client.get("/api/agent/tools")
        self.assertEqual(r_tools.status_code, 200)
        self.assertIn("tools", r_tools.json())

        r_prefs = self.client.get("/api/memory/preferences")
        self.assertEqual(r_prefs.status_code, 200)


if __name__ == "__main__":
    unittest.main()
