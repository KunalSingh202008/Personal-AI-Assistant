import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import database
from database import create_conversation, initialize_database
from memory.manager import MemoryManager
from research.agent import research_stream


class MemoryAndResearchTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.db_path = Path(cls.temp_dir.name) / "test_memory.db"
        cls.db_patch = patch.object(database, "DATABASE_PATH", cls.db_path)
        cls.db_patch.start()
        initialize_database()

    @classmethod
    def tearDownClass(cls):
        cls.db_patch.stop()
        cls.temp_dir.cleanup()

    def setUp(self):
        MemoryManager.clear_memory()

    def test_preferences_lifecycle(self):
        # 1. Set preference
        MemoryManager.set_preference("tone", "concise and technical", category="persona")
        MemoryManager.set_preference("code_style", "PEP8 with type hints", category="coding")

        prefs = MemoryManager.get_preferences()
        self.assertEqual(prefs.get("tone"), "concise and technical")
        self.assertEqual(prefs.get("code_style"), "PEP8 with type hints")

        # 2. Build context injection
        injection = MemoryManager.build_context_injection()
        self.assertIn("PERSISTENT USER PREFERENCES", injection)
        self.assertIn("concise and technical", injection)

        # 3. Export memory snapshot
        snapshot = MemoryManager.export_snapshot()
        self.assertEqual(snapshot["user_preferences"]["tone"], "concise and technical")
        self.assertIn("indexed_documents", snapshot)
        self.assertIn("database_connectors", snapshot)

        # 4. Remove preference
        deleted = MemoryManager.remove_preference("tone")
        self.assertTrue(deleted)
        after_prefs = MemoryManager.get_preferences()
        self.assertNotIn("tone", after_prefs)

        # 5. Clear memory
        MemoryManager.clear_memory()
        cleared_prefs = MemoryManager.get_preferences()
        self.assertEqual(len(cleared_prefs), 0)

    async def test_research_agent_stream_evidence_collection(self):
        class FakeStreamResponse:
            def raise_for_status(self):
                pass

            async def aiter_lines(self):
                events = [
                    {"message": {"content": "### Executive Summary\nAnalysis based on verified local knowledge [1].\n"}},
                    {"message": {"content": "### Verified Findings\nNexus AI is verified [1].\n"}},
                    {"done": True},
                ]
                for ev in events:
                    yield json.dumps(ev)

        class FakeClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            def stream(self, method, url, json=None):
                class StreamContext:
                    async def __aenter__(self_inner):
                        return FakeStreamResponse()

                    async def __aexit__(self_inner, *args):
                        pass

                return StreamContext()

        conv = create_conversation("Test Conversation")
        with patch("research.agent.httpx.AsyncClient", FakeClient):
            gen = research_stream(
                query="Tell me about Nexus AI architecture",
                conversation_id=conv["id"],
                turn_id="test-turn-1",
                workspace_path=".",
                depth="quick",
            )
            events = []
            async for line in gen:
                if line.strip():
                    events.append(json.loads(line))

            event_types = [e.get("type") for e in events if "type" in e]
            self.assertIn("research_plan", event_types)
            self.assertIn("research_step", event_types)
            self.assertIn("evidence_summary", event_types)

            # Check tokens or done
            has_done = any(e.get("done") for e in events)
            self.assertTrue(has_done)


if __name__ == "__main__":
    unittest.main()
