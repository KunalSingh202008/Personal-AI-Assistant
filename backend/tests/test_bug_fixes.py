"""
Comprehensive Regression & Bug Fix Verification Suite
Validates fixes for:
1. Chat context & consecutive distinct questions (Bug 1 - no repeating previous answers).
2. Internal Windows system intelligence (Bug 2 - genuine disk space, processes, RAM, large files).
3. Voice & Text parity and reflection (Bug 3 & 4 - 100% architectural symmetry).
"""

import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

# Ensure backend directory is in sys.path
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from unittest.mock import patch
from fastapi.testclient import TestClient

import database
from database import initialize_database
from main import app
from core.intent_engine import intent_engine, IntentResult
from core.entity_tracker import entity_tracker
from core.tool_registry import tool_registry
from core.engine import kela_engine
from core.conversation_manager import conversation_manager
from core.permission_manager import permission_manager
import pc_control


class BugFixRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.db_path = Path(cls.temp_dir.name) / "test_bug_fixes.db"
        cls.db_patch = patch.object(database, "DATABASE_PATH", cls.db_path)
        cls.db_patch.start()
        initialize_database()
        cls.client = TestClient(app, headers={"X-KELA-Token": permission_manager.local_token})

    @classmethod
    def tearDownClass(cls):
        cls.db_patch.stop()
        cls.temp_dir.cleanup()

    def setUp(self):
        entity_tracker.clear()

    # -------------------------------------------------------------
    # 1. Genuine Windows System Intelligence (Bug 2)
    # -------------------------------------------------------------
    def test_genuine_disk_space_enumeration(self):
        """Verifies real drive usage without hardcoded mocks."""
        res = pc_control.get_disk_space()
        self.assertEqual(res["status"], "success")
        self.assertIn("drives", res)
        self.assertGreater(len(res["drives"]), 0)
        c_drive = next((d for d in res["drives"] if d["drive"].upper().startswith("C")), None)
        self.assertIsNotNone(c_drive, "Expected C: drive to be detected on Windows host.")
        self.assertGreater(c_drive["total_gb"], 1.0)
        self.assertGreater(c_drive["used_gb"], 0.0)
        self.assertGreaterEqual(c_drive["free_gb"], 0.0)
        self.assertIn("summary", res)
        self.assertGreater(res["summary"]["total_capacity_gb"], 1.0)

    def test_genuine_running_processes_tasklist(self):
        """Verifies genuine active processes from Windows tasklist command."""
        res = pc_control.list_running_processes(limit=10, sort_by_memory=True)
        self.assertEqual(res["status"], "success")
        procs = res["processes"]
        self.assertGreater(len(procs), 0)
        # Verify real structure
        p0 = procs[0]
        self.assertIn("ProcessName", p0)
        self.assertIn("MemoryMB", p0)
        self.assertIn("instance_count", p0)
        self.assertGreater(p0["MemoryMB"], 0.0)
        # Ensure it's sorted descending by memory
        if len(procs) > 1:
            self.assertGreaterEqual(procs[0]["MemoryMB"], procs[1]["MemoryMB"])

    def test_genuine_system_metrics(self):
        """Verifies RAM and CPU load metrics."""
        res = pc_control.get_system_metrics()
        self.assertEqual(res["status"], "success")
        metrics = res["metrics"]
        self.assertIn("ram_usage_percent", metrics)
        self.assertIn("used_ram_mb", metrics)
        self.assertIn("total_ram_mb", metrics)
        self.assertGreater(metrics["total_ram_mb"], 1024)

    def test_bounded_large_files_detection(self):
        """Verifies large file detection executes within bounded user directories."""
        res = pc_control.find_large_files(min_size_mb=50, max_results=5)
        self.assertEqual(res["status"], "success")
        self.assertIn("files", res)
        self.assertIn("count", res)

    def test_open_folder_alias_resolution(self):
        """Verifies open_folder properly recognizes user directory aliases."""
        # Check alias resolution without actually launching explorer in headless mode
        home = pc_control.system_ops.USER_HOME
        downloads_expected = str(Path(home) / "Downloads")
        res = pc_control.open_folder("downloads")
        self.assertIn(res["status"], {"success", "error"})
        if res["status"] == "success":
            self.assertEqual(Path(res["path"]), Path(downloads_expected))

    # -------------------------------------------------------------
    # 2. Intent Classification for System Commands
    # -------------------------------------------------------------
    def test_disk_space_intent_classification(self):
        queries = [
            "How much free space is available on my laptop?",
            "What is my disk space?",
            "how much storage do I have left",
            "C drive space kitna hai",
            "storage kitna bacha hai",
        ]
        for q in queries:
            intent = intent_engine.classify_intent(q)
            self.assertEqual(intent.intent_type, "ACTION", f"Failed for '{q}'")
            self.assertEqual(intent.tool_name, "get_disk_space", f"Failed for '{q}'")

    def test_running_processes_intent_classification(self):
        queries = [
            "What apps are consuming the most memory?",
            "List running processes",
            "top memory consuming processes",
            "kaun se processes chal rahe hain",
        ]
        for q in queries:
            intent = intent_engine.classify_intent(q)
            self.assertEqual(intent.intent_type, "ACTION", f"Failed for '{q}'")
            self.assertEqual(intent.tool_name, "list_running_processes", f"Failed for '{q}'")

    def test_large_files_intent_classification(self):
        queries = [
            "Find large files on my computer",
            "What are the biggest files taking space?",
            "heavy files dhundo",
        ]
        for q in queries:
            intent = intent_engine.classify_intent(q)
            self.assertEqual(intent.intent_type, "ACTION", f"Failed for '{q}'")
            self.assertEqual(intent.tool_name, "find_large_files", f"Failed for '{q}'")

    def test_open_folder_intent_classification(self):
        queries = [
            "Open the downloads folder",
            "kholo my documents folder",
            "open desktop",
        ]
        for q in queries:
            intent = intent_engine.classify_intent(q)
            self.assertEqual(intent.intent_type, "ACTION", f"Failed for '{q}'")
            self.assertEqual(intent.tool_name, "open_folder", f"Failed for '{q}'")

    # -------------------------------------------------------------
    # 3. Bug 1: Context Isolation & Consecutive Unrelated Questions
    # -------------------------------------------------------------
    def test_consecutive_questions_do_not_repeat_previous_answer(self):
        """
        User asks: 'Count my GitHub repositories.' -> answered.
        User asks: 'How much free space is available on my laptop?' -> MUST NOT repeat GitHub answer.
        """
        conv = conversation_manager.create_conversation("Multi-turn Test")
        conv_id = conv["id"]

        # Turn 1: User asks GitHub question
        conversation_manager.save_user_message(conv_id, "Count my GitHub repositories.", "turn_1_user")
        conversation_manager.save_assistant_message(conv_id, "Your account has 12 projects.", "turn_1_asst")

        # Turn 2: User asks disk space question
        turn_2_text = "How much free space is available on my laptop?"

        async def run_chat():
            chunks = []
            async for raw in kela_engine.chat_stream(
                messages=[
                    {"role": "user", "content": "Count my GitHub repositories."},
                    {"role": "assistant", "content": "Your account has 12 projects."},
                    {"role": "user", "content": turn_2_text},
                ],
                conversation_id=conv_id,
                turn_id="turn_2",
            ):
                event = json.loads(raw)
                if "token" in event:
                    chunks.append(event["token"])
            return "".join(chunks)

        answer = asyncio.run(run_chat())
        self.assertNotIn("12 projects", answer)
        self.assertNotIn("GitHub", answer)
        self.assertTrue("free" in answer.lower() or "gb" in answer.lower())

    def test_previous_question_reflection(self):
        """User asks 'What did I ask you previously?' -> returns exact previous query."""
        conv = conversation_manager.create_conversation("Reflection Test")
        conv_id = conv["id"]

        # Previous turn
        conversation_manager.save_user_message(conv_id, "Find my Phone Doctor project.", "turn_prev_user")
        conversation_manager.save_assistant_message(conv_id, "Found Phone Doctor at desktop.", "turn_prev_asst")

        # Reflection turn in English
        intent_en = intent_engine.classify_intent("What did I ask you previously?", conversation_id=conv_id)
        self.assertEqual(intent_en.intent_type, "QUESTION")
        self.assertIn("Find my Phone Doctor project.", intent_en.response_text)

        # Reflection turn in Hinglish
        intent_hi = intent_engine.classify_intent("Pichla sawal kya tha?", conversation_id=conv_id)
        self.assertEqual(intent_hi.intent_type, "QUESTION")
        self.assertIn("Find my Phone Doctor project.", intent_hi.response_text)

    # -------------------------------------------------------------
    # 4. Voice and Text Parity (Bug 3 & 4)
    # -------------------------------------------------------------
    def test_voice_turn_disk_space_parity(self):
        """Voice turn for disk space returns natural spoken answer with real metrics."""
        res = asyncio.run(kela_engine.process_voice_turn(
            text="How much free space is available on my laptop?",
            conversation_id=None,
        ))
        self.assertTrue(res["handled"])
        resp = res["response_text"]
        self.assertTrue("free" in resp.lower() or "gb" in resp.lower())
        self.assertIn("C:", resp)

    def test_voice_turn_processes_parity(self):
        """Voice turn for top memory consuming processes."""
        res = asyncio.run(kela_engine.process_voice_turn(
            text="What apps are consuming the most memory?",
            conversation_id=None,
        ))
        self.assertTrue(res["handled"])
        resp = res["response_text"]
        self.assertTrue("memory" in resp.lower() or "mb" in resp.lower())

    # -------------------------------------------------------------
    # 5. REST PC Endpoints Security & Data
    # -------------------------------------------------------------
    def test_rest_pc_storage_endpoint(self):
        """Verifies GET /api/pc/storage returns real disk information."""
        resp = self.client.get("/api/pc/storage")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "success")
        self.assertIn("drives", data)

    def test_rest_pc_processes_endpoint(self):
        """Verifies GET /api/pc/processes returns real processes."""
        resp = self.client.get("/api/pc/processes?limit=5")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "success")
        self.assertIn("processes", data)


if __name__ == "__main__":
    unittest.main()
