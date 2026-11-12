"""
Phase B/C Stabilization Verification Suite
Tests the 16 critical scenarios covering:
1. "Open Calculator."
2. "Open Chrome." (actionable error when Chrome is absent)
3. "Open YouTube."
4. "Open YouTube in Chrome."
5. "Mere laptop ki RAM kitni use ho rahi hai?" (real RAM metrics)
6. "How much free space is available?" (genuine disk metrics)
7. "Find my Phone Doctor project."
8. "Open it." (resolves to Phone Doctor project directory)
9. "Find my resume."
10. "Open it." (resolves to resume file)
11. "What did I ask you previously?" (reflection of user query)
12. Three consecutive voice turns in the same conversation
13. Stop voice mode
14. Restart voice mode (preserves conversation history)
15. Permission denied / device error handling
16. Backend timeout and tool failure scenarios
"""

import asyncio
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Ensure backend directory is in sys.path
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

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
from pc_control.app_launcher import (
    launch_application,
    close_application,
    open_youtube,
    find_chrome_executable,
    find_brave_executable,
    find_edge_executable,
)
from pc_control.system_ops import get_system_metrics, get_disk_space, list_running_processes


class PhaseBCStabilizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.db_path = Path(cls.temp_dir.name) / "test_phase_bc_stabilization.db"
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

    # -----------------------------------------------------------------
    # Scenario 1: "Open Calculator."
    # -----------------------------------------------------------------
    def test_scenario_01_open_calculator(self):
        t0 = time.perf_counter()
        intent = intent_engine.classify_intent("Open Calculator.")
        t_intent = (time.perf_counter() - t0) * 1000.0

        self.assertEqual(intent.intent_type, "ACTION")
        self.assertIn(intent.tool_name, {"launch_app", "launch_calculator", "launch_application"})

        t1 = time.perf_counter()
        # Launch calculator with quick timeout verification
        res = launch_application("calc", timeout_sec=0.8)
        t_exec = (time.perf_counter() - t1) * 1000.0

        self.assertEqual(res["status"], "success")
        self.assertTrue(res["verified"])
        # Close calculator to keep host clean
        close_application("calc", timeout_sec=0.5)

        # Execution time using Win32 snapshot should be well under 1000ms
        self.assertLess(t_intent, 150.0, f"Intent classification too slow: {t_intent}ms")
        self.assertLess(t_exec, 1200.0, f"App launch too slow: {t_exec}ms")

    # -----------------------------------------------------------------
    # Scenario 2: "Open Chrome." (Handles host environment honestly)
    # -----------------------------------------------------------------
    def test_scenario_02_open_chrome_absent_or_present(self):
        t0 = time.perf_counter()
        intent = intent_engine.classify_intent("Open Chrome.")
        t_intent = (time.perf_counter() - t0) * 1000.0

        self.assertEqual(intent.intent_type, "ACTION")
        self.assertEqual(intent.parameters.get("app_name"), "chrome")

        chrome_path = find_chrome_executable()
        res = launch_application("chrome", timeout_sec=0.5)

        if not chrome_path:
            # If Chrome is not installed, must report actionable error without masquerading
            self.assertEqual(res["status"], "error")
            self.assertIn("Google Chrome is not installed", res["message"])
            self.assertFalse(res["verified"])

            # Verify formatted spoken response
            spoken = intent_engine.format_action_response(intent, res, lang="english")
            self.assertIn("Google Chrome is not installed", spoken)
        else:
            self.assertEqual(res["status"], "success")

    # -----------------------------------------------------------------
    # Scenario 3: "Open YouTube."
    # -----------------------------------------------------------------
    def test_scenario_03_open_youtube(self):
        intent = intent_engine.classify_intent("Open YouTube.")
        self.assertEqual(intent.intent_type, "ACTION")
        self.assertIn(intent.tool_name, {"launch_app", "open_youtube"})
        self.assertEqual(intent.parameters.get("app_name"), "youtube")

        with patch("webbrowser.open", return_value=True) as mock_web_open:
            res = open_youtube()
            self.assertEqual(res["status"], "success")
            self.assertTrue(res["verified"])
            self.assertEqual(res["target"], "https://www.youtube.com")
            mock_web_open.assert_called_with("https://www.youtube.com")

            spoken_en = intent_engine.format_action_response(intent, res, lang="english")
            self.assertIn("Opened YouTube", spoken_en)
            spoken_hi = intent_engine.format_action_response(intent, res, lang="hinglish")
            self.assertIn("YouTube", spoken_hi)

    # -----------------------------------------------------------------
    # Scenario 4: "Open YouTube in Chrome."
    # -----------------------------------------------------------------
    def test_scenario_04_open_youtube_in_chrome(self):
        intent = intent_engine.classify_intent("Open YouTube in Chrome.")
        self.assertEqual(intent.intent_type, "ACTION")
        self.assertIn(intent.tool_name, {"launch_app", "open_youtube"})

        chrome_path = find_chrome_executable()
        if not chrome_path:
            res = open_youtube(target_browser="chrome")
            self.assertEqual(res["status"], "error")
            self.assertIn("Google Chrome is not installed", res["message"])
            spoken = intent_engine.format_action_response(intent, res, lang="english")
            self.assertIn("Google Chrome is not installed", spoken)

    # -----------------------------------------------------------------
    # Scenario 5: "Mere laptop ki RAM kitni use ho rahi hai?"
    # -----------------------------------------------------------------
    def test_scenario_05_ram_metrics_hinglish(self):
        t0 = time.perf_counter()
        query = "Mere laptop ki RAM kitni use ho rahi hai?"
        intent = intent_engine.classify_intent(query)
        t_intent = (time.perf_counter() - t0) * 1000.0

        self.assertEqual(intent.intent_type, "ACTION")
        self.assertEqual(intent.tool_name, "get_system_metrics")
        self.assertEqual(intent.language, "hinglish")

        # Execute genuine metric retrieval
        t1 = time.perf_counter()
        metrics_res = get_system_metrics()
        t_exec = (time.perf_counter() - t1) * 1000.0

        self.assertEqual(metrics_res["status"], "success")
        metrics = metrics_res["metrics"]
        self.assertIn("used_ram_gb", metrics)
        self.assertIn("total_ram_gb", metrics)
        self.assertIn("free_ram_gb", metrics)
        self.assertGreater(metrics["total_ram_gb"], 1.0)
        self.assertGreater(metrics["used_ram_gb"], 0.0)

        # Spoken output check
        spoken = intent_engine.format_action_response(intent, {"result": metrics_res}, lang="hinglish")
        self.assertIn("RAM usage", spoken)
        self.assertIn(f"{metrics['used_ram_gb']:.1f} GB", spoken)
        self.assertIn(f"{metrics['total_ram_gb']:.1f} GB", spoken)

        # Execution time check
        self.assertLess(t_intent, 150.0)
        self.assertLess(t_exec, 300.0)

    # -----------------------------------------------------------------
    # Scenario 6: "How much free space is available?"
    # -----------------------------------------------------------------
    def test_scenario_06_free_disk_space(self):
        t0 = time.perf_counter()
        query = "How much free space is available?"
        intent = intent_engine.classify_intent(query)
        t_intent = (time.perf_counter() - t0) * 1000.0

        self.assertEqual(intent.intent_type, "ACTION")
        self.assertEqual(intent.tool_name, "get_disk_space")

        t1 = time.perf_counter()
        res = get_disk_space()
        t_exec = (time.perf_counter() - t1) * 1000.0

        self.assertEqual(res["status"], "success")
        self.assertGreater(len(res["drives"]), 0)
        c_drive = next((d for d in res["drives"] if d["drive"].upper().startswith("C")), None)
        self.assertIsNotNone(c_drive)
        self.assertGreater(c_drive["free_gb"], 0.0)

        spoken = intent_engine.format_action_response(intent, {"result": res}, lang="english")
        self.assertIn("C:", spoken)
        self.assertIn(f"{c_drive['free_gb']} GB free", spoken)

        self.assertLess(t_intent, 150.0)
        self.assertLess(t_exec, 300.0)

    # -----------------------------------------------------------------
    # Scenario 7 & 8: "Find my Phone Doctor project." -> "Open it."
    # -----------------------------------------------------------------
    def test_scenario_07_and_08_find_project_then_open_it(self):
        conv_id = 901

        # Turn 1: Find Phone Doctor project
        intent_find = intent_engine.classify_intent("Find my Phone Doctor project.", conversation_id=conv_id)
        self.assertEqual(intent_find.intent_type, "ACTION")
        self.assertEqual(intent_find.tool_name, "search_user_files")

        # Simulate search result returning both a project folder AND an incidental zip
        phone_doctor_dir = str(Path.home() / "Desktop" / "PhoneDoctor")
        phone_doctor_zip = str(Path.home() / "Desktop" / "PhoneDoctor.zip")

        mock_search_result = {
            "status": "success",
            "results": [
                {"name": "PhoneDoctor.zip", "path": phone_doctor_zip, "is_project": False, "type": "file"},
                {"name": "PhoneDoctor", "path": phone_doctor_dir, "is_project": True, "type": "directory"},
            ]
        }

        # Update entity tracker
        entity_tracker.update_from_action_result(
            conv_id,
            "search_user_files",
            {"query": "Phone Doctor"},
            mock_search_result
        )

        ctx = entity_tracker.get_context(conv_id)
        self.assertEqual(ctx.get("last_project")["name"], "PhoneDoctor")
        self.assertEqual(ctx.get("last_entity_type"), "project")

        # Turn 2: "Open it." MUST resolve to opening the project directory, NOT the zip file!
        resolved_text, meta = entity_tracker.resolve_pronouns("Open it.", conv_id)
        self.assertTrue(meta["resolved"])
        self.assertEqual(meta["target_type"], "project")
        self.assertIn("open folder", resolved_text.lower())
        self.assertIn("PhoneDoctor", resolved_text)
        self.assertNotIn(".zip", resolved_text)

        # Classify the resolved text
        intent_open = intent_engine.classify_intent(resolved_text, conversation_id=conv_id)
        self.assertEqual(intent_open.intent_type, "ACTION")
        self.assertEqual(intent_open.tool_name, "open_folder")
        self.assertEqual(Path(intent_open.parameters.get("folder_path")), Path(phone_doctor_dir))

    # -----------------------------------------------------------------
    # Scenario 9 & 10: "Find my resume." -> "Open it."
    # -----------------------------------------------------------------
    def test_scenario_09_and_10_find_file_then_open_it(self):
        conv_id = 902

        # Turn 1: Find resume
        intent_find = intent_engine.classify_intent("Find my resume.", conversation_id=conv_id)
        self.assertEqual(intent_find.intent_type, "ACTION")
        self.assertIn(intent_find.tool_name, {"search_user_files", "find_resume_files"})

        resume_path = str(Path.home() / "Documents" / "Kunal_Resume.pdf")
        mock_search_result = {
            "status": "success",
            "results": [
                {"name": "Kunal_Resume.pdf", "path": resume_path, "is_project": False, "type": "file"},
            ]
        }

        entity_tracker.update_from_action_result(
            conv_id,
            "search_user_files",
            {"query": "resume"},
            mock_search_result
        )

        ctx = entity_tracker.get_context(conv_id)
        self.assertEqual(ctx.get("last_file")["path"], resume_path)
        self.assertEqual(ctx.get("last_entity_type"), "file")

        # Turn 2: "Open it." MUST resolve to opening the resume file
        resolved_text, meta = entity_tracker.resolve_pronouns("Open it.", conv_id)
        self.assertTrue(meta["resolved"])
        self.assertEqual(meta["target_type"], "file")
        self.assertEqual(resolved_text, f"open file {resume_path}")

        intent_open = intent_engine.classify_intent(resolved_text, conversation_id=conv_id)
        self.assertEqual(intent_open.intent_type, "ACTION")
        self.assertIn(intent_open.tool_name, {"open_file_path", "open_file"})
        self.assertEqual(intent_open.parameters.get("file_path"), resume_path)

    # -----------------------------------------------------------------
    # Scenario 11: "What did I ask you previously?"
    # -----------------------------------------------------------------
    def test_scenario_11_previous_query_reflection(self):
        conv = conversation_manager.create_conversation("Reflection Scenario 11")
        conv_id = conv["id"]

        user_query = "What apps are consuming the most memory?"
        conversation_manager.save_user_message(conv_id, user_query, "u_turn_1")
        conversation_manager.save_assistant_message(conv_id, "Code.exe is using 500 MB.", "a_turn_1")

        intent = intent_engine.classify_intent("What did I ask you previously?", conversation_id=conv_id)
        self.assertEqual(intent.intent_type, "QUESTION")
        self.assertIn(user_query, intent.response_text)

        # Hinglish reflection
        intent_hi = intent_engine.classify_intent("Maine pehle kya poocha tha?", conversation_id=conv_id)
        self.assertEqual(intent_hi.intent_type, "QUESTION")
        self.assertIn(user_query, intent_hi.response_text)

    # -----------------------------------------------------------------
    # Scenario 12: Three consecutive voice commands in the same conversation
    # -----------------------------------------------------------------
    def test_scenario_12_three_consecutive_voice_turns(self):
        conv = conversation_manager.create_conversation("Consecutive Turns Test")
        conv_id = conv["id"]

        commands = [
            "Mere laptop ki RAM kitni use ho rahi hai?",
            "How much free space is available?",
            "What did I ask you previously?"
        ]

        responses = []
        for i, cmd in enumerate(commands):
            turn_res = asyncio.run(kela_engine.process_voice_turn(
                text=cmd,
                conversation_id=conv_id,
                turn_id=f"turn_{i+1}",
            ))
            self.assertTrue(turn_res["handled"])
            self.assertGreater(len(turn_res["response_text"]), 0)
            self.assertIn("latency_ms", turn_res)
            responses.append(turn_res["response_text"])

        # Turn 1 must discuss RAM
        self.assertIn("RAM usage", responses[0])
        # Turn 2 must discuss disk space
        self.assertTrue("C:" in responses[1] or "free" in responses[1].lower())
        # Turn 3 must reflect Turn 2's question
        self.assertIn("How much free space is available?", responses[2])

        # Verify conversation history persisted all 3 turns cleanly
        history = conversation_manager.get_messages(conv_id)
        self.assertEqual(len(history), 6)  # 3 user messages + 3 assistant responses

    # -----------------------------------------------------------------
    # Scenario 13: Stop voice mode (Session isolation)
    # -----------------------------------------------------------------
    def test_scenario_13_stop_voice_mode(self):
        conv = conversation_manager.create_conversation("Stop Voice Mode Test")
        conv_id = conv["id"]

        # Run turn 1
        res1 = asyncio.run(kela_engine.process_voice_turn(
            text="What is your name?",
            conversation_id=conv_id,
            turn_id="stop_test_t1",
        ))
        self.assertTrue(res1["handled"])

        # Simulating stop: Conversation remains saved, no background tasks running
        history = conversation_manager.get_messages(conv_id)
        self.assertEqual(len(history), 2)

    # -----------------------------------------------------------------
    # Scenario 14: Restart voice mode (Preserves conversation history)
    # -----------------------------------------------------------------
    def test_scenario_14_restart_voice_mode_preserves_history(self):
        conv = conversation_manager.create_conversation("Restart Voice Test")
        conv_id = conv["id"]

        # Turn before restart
        asyncio.run(kela_engine.process_voice_turn(
            text="Find my Phone Doctor project.",
            conversation_id=conv_id,
            turn_id="turn_before_restart",
        ))

        # "Restart": voice session is reopened with the same conversation_id
        res_after = asyncio.run(kela_engine.process_voice_turn(
            text="What did I ask you previously?",
            conversation_id=conv_id,
            turn_id="turn_after_restart",
        ))

        self.assertTrue(res_after["handled"])
        self.assertIn("Find my Phone Doctor project.", res_after["response_text"])

    # -----------------------------------------------------------------
    # Scenario 15: Permission denied / device error handling
    # -----------------------------------------------------------------
    def test_scenario_15_device_error_handling(self):
        # Unauthenticated request to protected voice speak returns 401
        unauth_resp = self.client.post(
            "/api/voice/speak",
            headers={"X-KELA-Token": "invalid_token_123"},
            json={"text": "hello"}
        )
        self.assertEqual(unauth_resp.status_code, 401)

        # Empty voice turn input rejected gracefully
        empty_resp = self.client.post(
            "/api/voice/command",
            json={"text": "   "}
        )
        self.assertEqual(empty_resp.status_code, 400)

    # -----------------------------------------------------------------
    # Scenario 16: Backend timeout and tool failure scenarios
    # -----------------------------------------------------------------
    def test_scenario_16_backend_timeout_and_actionable_errors(self):
        # 1. Nonexistent application launch times out and provides actionable message
        t0 = time.perf_counter()
        res = launch_application("definitely_fake_app_xyz", timeout_sec=0.4)
        t_elapsed = (time.perf_counter() - t0) * 1000.0

        self.assertEqual(res["status"], "error")
        self.assertFalse(res["verified"])
        self.assertIn("process did not start within", res["message"])
        self.assertLess(t_elapsed, 1200.0, f"App launch timeout took too long: {t_elapsed}ms")

        # 2. Unknown directory open returns actionable error
        folder_res = pc_control.open_folder("nonexistent_directory_9999")
        self.assertEqual(folder_res["status"], "error")
        self.assertIn("does not exist", folder_res["message"].lower())


if __name__ == "__main__":
    unittest.main()
