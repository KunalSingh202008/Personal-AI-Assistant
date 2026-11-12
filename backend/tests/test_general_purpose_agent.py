"""
General-Purpose Windows AI Agent Verification Suite
Tests the 17 required scenarios:
1. "Open YouTube."
2. "Open Edge."
3. "Open Brave."
4. "Open YouTube in Brave."
5. Request a browser that is not installed.
6. "How much RAM is being used?"
7. "Which drive is almost full?"
8. "Find my largest files."
9. "Find duplicate files."
10. "Analyse my laptop and suggest improvements."
11. "Which files can I safely review for cleanup?"
12. "Find Phone Doctor."
13. "Open it."
14. "Analyse this project's folder."
15. Ask a follow-up about a previously identified file.
16. Perform multiple consecutive voice commands.
17. Verify that destructive actions cannot occur without approval.
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
    launch_browser,
    find_installed_browsers,
    find_chrome_executable,
    find_brave_executable,
    find_edge_executable,
    get_installed_applications,
    get_startup_applications,
)
from pc_control.storage_analyzer import (
    find_duplicate_files,
    identify_temporary_files,
    analyze_storage_cleanup,
    analyze_project_folder,
    recycle_file_safely,
)
from pc_control.task_planner import task_planner


class GeneralPurposeAgentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.db_path = Path(cls.temp_dir.name) / "test_general_purpose.db"
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
    # Scenario 1: "Open YouTube."
    # -------------------------------------------------------------
    def test_scenario_01_open_youtube(self):
        query = "Open YouTube."
        intent = intent_engine.classify_intent(query)
        self.assertEqual(intent.intent_type, "ACTION")
        self.assertIn(intent.tool_name, {"launch_app", "launch_browser", "open_youtube"})

        with patch("webbrowser.open", return_value=True) as mock_web:
            res = pc_control.launch_application("youtube")
            self.assertEqual(res["status"], "success")
            self.assertTrue(res["verified"])
            spoken = intent_engine.format_action_response(intent, {"result": res}, lang="english")
            self.assertIn("YouTube", spoken)

    # -------------------------------------------------------------
    # Scenario 2: "Open Edge."
    # -------------------------------------------------------------
    def test_scenario_02_open_edge(self):
        query = "Open Edge."
        intent = intent_engine.classify_intent(query)
        self.assertEqual(intent.intent_type, "ACTION")
        self.assertIn(intent.tool_name, {"launch_app", "launch_browser"})

        edge_exe = find_edge_executable()
        self.assertIsNotNone(edge_exe, "Microsoft Edge is expected on this Windows host")

        with patch("subprocess.Popen") as mock_popen:
            res = launch_browser("edge")
            self.assertEqual(res["status"], "success")
            self.assertEqual(res["browser"], "Microsoft Edge")
            spoken = intent_engine.format_action_response(intent, {"result": res}, lang="english")
            self.assertIn("Microsoft Edge", spoken)

    # -------------------------------------------------------------
    # Scenario 3: "Open Brave."
    # -------------------------------------------------------------
    def test_scenario_03_open_brave(self):
        query = "Open Brave."
        intent = intent_engine.classify_intent(query)
        self.assertEqual(intent.intent_type, "ACTION")
        self.assertIn(intent.tool_name, {"launch_app", "launch_browser"})

        brave_exe = find_brave_executable()
        self.assertIsNotNone(brave_exe, "Brave Browser is expected on this Windows host")

        with patch("subprocess.Popen") as mock_popen:
            res = launch_browser("brave")
            self.assertEqual(res["status"], "success")
            self.assertEqual(res["browser"], "Brave")
            spoken = intent_engine.format_action_response(intent, {"result": res}, lang="english")
            self.assertIn("Brave", spoken)

    # -------------------------------------------------------------
    # Scenario 4: "Open YouTube in Brave."
    # -------------------------------------------------------------
    def test_scenario_04_open_youtube_in_brave(self):
        query = "Open YouTube in Brave."
        intent = intent_engine.classify_intent(query)
        self.assertEqual(intent.intent_type, "ACTION")
        self.assertEqual(intent.parameters.get("browser_name"), "brave")

        with patch("subprocess.Popen") as mock_popen:
            res = launch_browser("brave", url="https://www.youtube.com")
            self.assertEqual(res["status"], "success")
            self.assertEqual(res["browser"], "Brave")
            self.assertIn("https://www.youtube.com", res["target"])
            spoken = intent_engine.format_action_response(intent, {"result": res}, lang="english")
            self.assertIn("YouTube in Brave", spoken)

    # -------------------------------------------------------------
    # Scenario 5: Request a browser that is not installed.
    # -------------------------------------------------------------
    def test_scenario_05_browser_not_installed(self):
        # Google Chrome is not installed on this host
        chrome_exe = find_chrome_executable()
        self.assertIsNone(chrome_exe, "Chrome is not installed on this machine")

        res = launch_browser("chrome")
        self.assertEqual(res["status"], "error")
        self.assertFalse(res["verified"])
        self.assertIn("Google Chrome is not installed on this computer", res["message"])
        self.assertIn("Available browsers:", res["message"])
        self.assertIn("Brave", res["message"])
        self.assertIn("Microsoft Edge", res["message"])

        # Also test arbitrary non-existent browser
        res_fake = launch_browser("super_fake_browser_123")
        self.assertEqual(res_fake["status"], "error")
        self.assertIn("not installed", res_fake["message"])

    # -------------------------------------------------------------
    # Scenario 6: "How much RAM is being used?"
    # -------------------------------------------------------------
    def test_scenario_06_ram_usage(self):
        query = "How much RAM is being used?"
        intent = intent_engine.classify_intent(query)
        self.assertEqual(intent.intent_type, "ACTION")
        self.assertEqual(intent.tool_name, "get_system_metrics")

        metrics_res = pc_control.get_system_metrics()
        self.assertEqual(metrics_res["status"], "success")
        metrics = metrics_res["metrics"]
        self.assertGreater(metrics["total_ram_gb"], 1.0)
        self.assertGreater(metrics["used_ram_gb"], 0.0)

        spoken = intent_engine.format_action_response(intent, {"result": metrics_res}, lang="english")
        self.assertIn("RAM usage", spoken)
        self.assertIn("GB", spoken)

    # -------------------------------------------------------------
    # Scenario 7: "Which drive is almost full?"
    # -------------------------------------------------------------
    def test_scenario_07_which_drive_is_almost_full(self):
        query = "Which drive is almost full?"
        intent = intent_engine.classify_intent(query)
        self.assertEqual(intent.intent_type, "ACTION")
        self.assertEqual(intent.tool_name, "get_disk_space")
        self.assertTrue(intent.parameters.get("almost_full_only"))

        disk_res = pc_control.get_disk_space()
        self.assertEqual(disk_res["status"], "success")
        self.assertIn("almost_full_drives", disk_res)

        spoken = intent_engine.format_action_response(intent, {"result": disk_res}, lang="english")
        self.assertIn("C:", spoken)
        self.assertIn("used", spoken.lower())

    # -------------------------------------------------------------
    # Scenario 8: "Find my largest files."
    # -------------------------------------------------------------
    def test_scenario_08_find_largest_files(self):
        query = "Find my largest files."
        intent = intent_engine.classify_intent(query)
        self.assertEqual(intent.intent_type, "ACTION")
        self.assertEqual(intent.tool_name, "find_large_files")

        res = pc_control.find_large_files(min_size_mb=10, max_results=5)
        self.assertEqual(res["status"], "success")
        self.assertIn("files", res)
        self.assertGreater(len(res["files"]), 0)

        spoken = intent_engine.format_action_response(intent, {"result": res}, lang="english")
        self.assertIn("large files", spoken.lower())

    # -------------------------------------------------------------
    # Scenario 9: "Find duplicate files."
    # -------------------------------------------------------------
    def test_scenario_09_find_duplicate_files(self):
        query = "Find duplicate files."
        intent = intent_engine.classify_intent(query)
        self.assertEqual(intent.intent_type, "ACTION")
        self.assertEqual(intent.tool_name, "find_duplicate_files")

        # Test duplicate detector with temp directory containing intentional duplicates
        with tempfile.TemporaryDirectory() as scan_dir:
            f1 = Path(scan_dir) / "original.dat"
            f2 = Path(scan_dir) / "copy.dat"
            data = b"identical_content_kela_test_bytes_" * 5000
            f1.write_bytes(data)
            f2.write_bytes(data)

            res = find_duplicate_files(directory=scan_dir, min_size_kb=10, max_results=5)
            self.assertEqual(res["status"], "success")
            self.assertEqual(res["duplicate_groups_count"], 1)
            group = res["duplicate_groups"][0]
            self.assertEqual(group["count"], 2)
            self.assertGreater(group["size_bytes"], 1024)

            spoken = intent_engine.format_action_response(intent, {"result": res}, lang="english")
            self.assertIn("duplicate", spoken.lower())

    # -------------------------------------------------------------
    # Scenario 10: "Analyse my laptop and suggest improvements."
    # -------------------------------------------------------------
    def test_scenario_10_analyse_laptop_and_suggest_improvements(self):
        query = "Analyse my laptop and suggest improvements."
        intent = intent_engine.classify_intent(query)
        self.assertEqual(intent.intent_type, "ACTION")
        self.assertEqual(intent.tool_name, "plan_system_diagnosis")

        res = task_planner.plan_system_diagnosis()
        self.assertEqual(res["status"], "success")
        self.assertIn("bottlenecks", res)
        self.assertIn("recommendations", res)
        self.assertGreater(len(res["recommendations"]), 0)
        self.assertIn("narrative", res)

        spoken = intent_engine.format_action_response(intent, {"result": res}, lang="english")
        self.assertTrue(len(spoken) > 20)

    # -------------------------------------------------------------
    # Scenario 11: "Which files can I safely review for cleanup?"
    # -------------------------------------------------------------
    def test_scenario_11_safely_review_for_cleanup(self):
        query = "Which files can I safely review for cleanup?"
        intent = intent_engine.classify_intent(query)
        self.assertEqual(intent.intent_type, "ACTION")
        self.assertEqual(intent.tool_name, "analyze_storage_cleanup")

        res = analyze_storage_cleanup()
        self.assertEqual(res["status"], "success")
        self.assertIn("safe_cleanup_candidates", res)
        self.assertIn("review_candidates", res)
        self.assertIn("safe_recovery_mb", res)

        spoken = intent_engine.format_action_response(intent, {"result": res}, lang="english")
        self.assertIn("Storage analysis", spoken)

    # -------------------------------------------------------------
    # Scenario 12 & 13: "Find Phone Doctor." -> "Open it."
    # -------------------------------------------------------------
    def test_scenario_12_and_13_find_phone_doctor_then_open_it(self):
        conv_id = 8801

        # Turn 1: Find Phone Doctor
        intent_find = intent_engine.classify_intent("Find Phone Doctor.", conversation_id=conv_id)
        self.assertEqual(intent_find.intent_type, "ACTION")
        self.assertEqual(intent_find.tool_name, "search_user_files")

        phone_doctor_dir = str(Path.home() / "Documents" / "phone-doctor")
        mock_result = {
            "status": "success",
            "results": [
                {"name": "phone-doctor", "path": phone_doctor_dir, "is_project": True, "type": "directory"},
            ]
        }
        entity_tracker.update_from_action_result(
            conv_id,
            "search_user_files",
            {"query": "Phone Doctor"},
            mock_result
        )

        ctx = entity_tracker.get_context(conv_id)
        self.assertEqual(ctx.get("last_project")["name"], "phone-doctor")
        self.assertEqual(ctx.get("last_entity_type"), "project")

        # Turn 2: "Open it." MUST resolve to opening the project directory
        resolved_text, meta = entity_tracker.resolve_pronouns("Open it.", conv_id)
        self.assertTrue(meta["resolved"])
        self.assertEqual(meta["target_type"], "project")

        intent_open = intent_engine.classify_intent(resolved_text, conversation_id=conv_id)
        self.assertEqual(intent_open.intent_type, "ACTION")
        self.assertEqual(intent_open.tool_name, "open_folder")
        self.assertEqual(Path(intent_open.parameters.get("folder_path")), Path(phone_doctor_dir))

    # -------------------------------------------------------------
    # Scenario 14: "Analyse this project's folder."
    # -------------------------------------------------------------
    def test_scenario_14_analyse_project_folder(self):
        conv_id = 8802
        current_project_dir = str(Path.cwd())
        entity_tracker.update_context(
            conv_id,
            last_project={"name": "Personal-AI-Assistant", "path": current_project_dir},
            last_entity_type="project"
        )

        # Pronoun resolution resolves "this project's folder"
        resolved_text, meta = entity_tracker.resolve_pronouns("Analyse this project's folder.", conv_id)
        self.assertTrue(meta["resolved"])
        self.assertEqual(meta["target_type"], "project")

        intent = intent_engine.classify_intent(resolved_text, conversation_id=conv_id)
        self.assertEqual(intent.intent_type, "ACTION")
        self.assertEqual(intent.tool_name, "analyze_project_folder")

        res = analyze_project_folder(current_project_dir)
        self.assertEqual(res["status"], "success")
        self.assertIn("tech_stack", res)
        self.assertIn("git_status", res)
        self.assertGreater(res["total_files"], 10)

        spoken = intent_engine.format_action_response(intent, {"result": res}, lang="english")
        self.assertIn("files", spoken)

    # -------------------------------------------------------------
    # Scenario 15: Ask a follow-up about a previously identified file.
    # -------------------------------------------------------------
    def test_scenario_15_conversational_follow_up(self):
        conv_id = 8803
        mock_candidates = [
            {"name": "installer_setup.exe", "path": "C:\\Users\\Kunal\\Downloads\\installer_setup.exe", "size_mb": 450.0, "category": "Installer", "risk": "LOW"},
            {"name": "temp_log.log", "path": "C:\\Users\\Kunal\\Downloads\\temp_log.log", "size_mb": 12.0, "category": "Temporary", "risk": "LOW"},
        ]
        entity_tracker.update_context(
            conv_id,
            last_file=mock_candidates[0],
            last_storage_candidates=mock_candidates,
            last_entity_type="file",
        )

        # Follow-up 1: "Show me the largest one."
        intent_largest = intent_engine.classify_intent("Show me the largest one.", conversation_id=conv_id)
        self.assertEqual(intent_largest.intent_type, "QUESTION")
        self.assertIn("installer_setup.exe", intent_largest.response_text)
        self.assertIn("450.0 MB", intent_largest.response_text)

        # Follow-up 2: "What happens if I delete this?"
        intent_delete_risk = intent_engine.classify_intent("What happens if I delete this?", conversation_id=conv_id)
        self.assertEqual(intent_delete_risk.intent_type, "QUESTION")
        self.assertIn("installer", intent_delete_risk.response_text.lower())
        self.assertIn("safe", intent_delete_risk.response_text.lower())

    # -------------------------------------------------------------
    # Scenario 16: Perform multiple consecutive voice commands.
    # -------------------------------------------------------------
    def test_scenario_16_multiple_consecutive_voice_commands(self):
        conv = conversation_manager.create_conversation("Consecutive General Voice")
        conv_id = conv["id"]

        queries = [
            "How much RAM is being used?",
            "Which drive is almost full?",
            "Analyse my laptop and suggest improvements.",
        ]

        for i, q in enumerate(queries):
            turn_res = asyncio.run(kela_engine.process_voice_turn(
                text=q,
                conversation_id=conv_id,
                turn_id=f"voice_consec_{i+1}",
            ))
            self.assertTrue(turn_res["handled"])
            self.assertGreater(len(turn_res["response_text"]), 0)
            self.assertIn("latency_ms", turn_res)

        msgs = conversation_manager.get_messages(conv_id)
        self.assertEqual(len(msgs), 6)  # 3 user messages + 3 assistant responses

    # -------------------------------------------------------------
    # Scenario 17: Verify destructive actions cannot occur without approval.
    # -------------------------------------------------------------
    def test_scenario_17_destructive_actions_blocked_without_approval(self):
        # 1. recycle_file_safely is classified as RED risk
        risk = tool_registry.get_tool_risk("recycle_file_safely")
        self.assertEqual(risk, "RED", "File recycling must be classified as RED risk")

        # 2. Voice turn blocks RED actions immediately
        voice_res = asyncio.run(kela_engine.process_voice_turn(
            text="Delete file definitely_real_document.pdf",
            conversation_id=None,
        ))
        # Ambiguous pronoun or blocked operation
        self.assertTrue(
            voice_res.get("clarification_needed") or not voice_res.get("handled") or voice_res.get("risk") == "RED"
        )

        # 3. Direct chat stream refuses RED actions
        conv = conversation_manager.create_conversation("Destructive Test")
        conv_id = conv["id"]

        async def run_chat():
            chunks = []
            async for raw in kela_engine.chat_stream(
                messages=[{"role": "user", "content": "delete file C:\\Users\\test.txt"}],
                conversation_id=conv_id,
            ):
                event = json.loads(raw)
                if "token" in event:
                    chunks.append(event["token"])
            return "".join(chunks)

        out = asyncio.run(run_chat())
        self.assertTrue("blocked" in out.lower() or "clarify" in out.lower() or "specify" in out.lower())


if __name__ == "__main__":
    unittest.main()
