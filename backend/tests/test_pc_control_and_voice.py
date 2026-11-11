import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient

import database
from database import initialize_database
from main import app
from voice.router import dispatch_voice_command, is_wake_word_present, detect_language

class PCControlAndVoiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.db_path = Path(cls.temp_dir.name) / "test_pc_voice.db"
        cls.db_patch = patch.object(database, "DATABASE_PATH", cls.db_path)
        cls.db_patch.start()
        initialize_database()
        from core.permission_manager import permission_manager
        cls.client = TestClient(app, headers={"X-KELA-Token": permission_manager.local_token})

    @classmethod
    def tearDownClass(cls):
        cls.db_patch.stop()
        cls.temp_dir.cleanup()

    def test_wake_word_and_language_detection(self):
        ww_found, query = is_wake_word_present("Hey KELA open calculator")
        self.assertTrue(ww_found)
        self.assertEqual(query, "open calculator")

        self.assertEqual(detect_language("open calculator"), "english")
        self.assertEqual(detect_language("battery kitni hai"), "hinglish")
        self.assertEqual(detect_language("kya samay hua hai"), "hinglish")

    def test_voice_command_fast_path(self):
        # Time command
        res = asyncio.run(dispatch_voice_command("what time is it"))
        self.assertTrue(res["handled"])
        self.assertTrue(res["fast_path"])
        self.assertIn("It is currently", res["response_text"])

        # Battery command
        res_bat = asyncio.run(dispatch_voice_command("battery kitni hai"))
        self.assertTrue(res_bat["handled"])
        self.assertEqual(res_bat["lang"], "hinglish")

        # Identity command
        res_id = asyncio.run(dispatch_voice_command("who am i"))
        self.assertTrue(res_id["handled"])
        self.assertIn("Kunal Singh", res_id["response_text"])

        # Projects command
        res_proj = asyncio.run(dispatch_voice_command("tell me about my projects"))
        self.assertTrue(res_proj["handled"])
        self.assertIn("Nexus AI", res_proj["response_text"])

        # Stop listening
        res_stop = asyncio.run(dispatch_voice_command("stop listening"))
        self.assertTrue(res_stop["handled"])
        self.assertTrue(res_stop.get("stop_session", False))

        # Web search command
        res_search = asyncio.run(dispatch_voice_command("search for python tutorials"))
        self.assertTrue(res_search["handled"])
        self.assertIn("action", res_search)

    def test_voice_api_endpoint(self):
        resp = self.client.post("/api/voice/command", json={"text": "what time is it"})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["handled"])
        self.assertEqual(data["action"], "time")

        # Test alias endpoint /api/voice/conversation
        resp2 = self.client.post("/api/voice/conversation", json={"text": "who am i"})
        self.assertEqual(resp2.status_code, 200)
        data2 = resp2.json()
        self.assertTrue(data2["handled"])
        self.assertIn("Kunal Singh", data2["response_text"])

    def test_voice_unification_with_core_engine_and_persistence(self):
        from core.conversation_manager import conversation_manager
        resp = self.client.post("/api/voice/conversation", json={"text": "what time is it"})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["handled"])
        self.assertIn("conversation_id", data)
        conv_id = data["conversation_id"]
        self.assertIsInstance(conv_id, int)

        # Verify messages persisted to SQLite
        messages = conversation_manager.get_messages(conv_id)
        self.assertGreaterEqual(len(messages), 2)
        user_msg = next((m for m in messages if m["role"] == "user"), None)
        asst_msg = next((m for m in messages if m["role"] == "assistant"), None)
        self.assertIsNotNone(user_msg)
        self.assertIsNotNone(asst_msg)
        self.assertEqual(user_msg["content"], "what time is it")
        self.assertIn("It is currently", asst_msg["content"])

    def test_voice_and_text_shared_session_history(self):
        from core.conversation_manager import conversation_manager
        # Create a conversation
        conv = conversation_manager.create_conversation(title="Shared Text and Voice")
        conv_id = conv["id"]

        # Voice turn 1
        resp1 = self.client.post(
            "/api/voice/conversation",
            json={"text": "who am i", "conversation_id": conv_id, "turn_id": "turn_voice_1"},
        )
        self.assertEqual(resp1.status_code, 200)
        d1 = resp1.json()
        self.assertEqual(d1["conversation_id"], conv_id)

        # Voice turn 2 in same session
        resp2 = self.client.post(
            "/api/voice/conversation",
            json={"text": "tell me about my projects", "conversation_id": conv_id, "turn_id": "turn_voice_2"},
        )
        self.assertEqual(resp2.status_code, 200)
        d2 = resp2.json()
        self.assertEqual(d2["conversation_id"], conv_id)

        # Verify all turns exist in the shared SQLite session
        messages = conversation_manager.get_messages(conv_id)
        self.assertEqual(len(messages), 4)
        roles = [m["role"] for m in messages]
        self.assertEqual(roles, ["user", "assistant", "user", "assistant"])
        self.assertEqual(messages[0]["content"], "who am i")
        self.assertIn("Kunal Singh", messages[1]["content"])
        self.assertEqual(messages[2]["content"], "tell me about my projects")
        self.assertIn("Nexus AI", messages[3]["content"])

    def test_voice_action_tool_risk_enforcement(self):
        from core.tool_registry import tool_registry

        # GREEN: Safe voice action is allowlisted
        self.assertEqual(tool_registry.get_tool_risk("launch_calculator"), "GREEN")
        self.assertEqual(tool_registry.get_tool_risk("time"), "GREEN")
        self.assertEqual(tool_registry.get_tool_risk("battery_status"), "GREEN")
        self.assertTrue(tool_registry.is_safe_voice_action("launch_calculator"))

        # AMBER: Risky action requires approval
        self.assertEqual(tool_registry.get_tool_risk("write_file"), "AMBER")
        self.assertEqual(tool_registry.get_tool_risk("run_command"), "AMBER")

        # RED: Destructive / unknown action is blocked
        self.assertEqual(tool_registry.get_tool_risk("format_drive"), "RED")

    def test_voice_turn_deduplication(self):
        from core.conversation_manager import conversation_manager
        conv = conversation_manager.create_conversation(title="Deduplication Test")
        conv_id = conv["id"]
        turn_id = "duplicate_turn_test_123"

        # First execution succeeds
        resp1 = self.client.post(
            "/api/voice/conversation",
            json={"text": "what time is it", "conversation_id": conv_id, "turn_id": turn_id},
        )
        self.assertEqual(resp1.status_code, 200)
        d1 = resp1.json()
        self.assertTrue(d1["handled"])

        # Manually lock turn to simulate active concurrency
        conversation_manager.acquire_turn_lock(conv_id, turn_id)
        try:
            resp2 = self.client.post(
                "/api/voice/conversation",
                json={"text": "what time is it", "conversation_id": conv_id, "turn_id": turn_id},
            )
            self.assertEqual(resp2.status_code, 200)
            d2 = resp2.json()
            self.assertFalse(d2["handled"])
            self.assertEqual(d2.get("action"), "duplicate_suppressed")
        finally:
            conversation_manager.release_turn_lock(conv_id, turn_id)

    def test_unauthenticated_pc_endpoint_blocked(self):
        unauth_client = TestClient(app)
        resp = unauth_client.get("/api/pc/system")
        self.assertEqual(resp.status_code, 401)

    def test_pc_system_endpoint(self):
        resp = self.client.get("/api/pc/system")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("metrics", data)
        self.assertIn("total_ram_mb", data["metrics"])

    def test_pc_processes_endpoint(self):
        resp = self.client.get("/api/pc/processes?limit=5")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "success")
        self.assertTrue(len(data["processes"]) > 0)

    def test_pc_search_endpoint(self):
        resp = self.client.post("/api/pc/search", json={"query": "test", "max_results": 5})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "success")

    def test_voice_hardware_endpoint(self):
        resp = self.client.get("/api/voice/hardware")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("browser_web_speech"))
        self.assertIn("windows_sapi_available", data)

    def test_pc_launch_verification(self):
        from pc_control.app_launcher import launch_application, close_application
        res = launch_application("calc")
        self.assertEqual(res["status"], "success")
        self.assertTrue(res["verified"])
        self.assertIn("pids", res)
        # Cleanup
        close_res = close_application("calc")
        self.assertEqual(close_res["status"], "success")
        self.assertTrue(close_res["verified"])

    def test_pc_launch_timeout_and_actionable_error(self):
        from pc_control.app_launcher import launch_application
        res = launch_application("nonexistent_test_app_404", timeout_sec=0.5)
        self.assertEqual(res["status"], "error")
        self.assertFalse(res["verified"])
        self.assertIn("process did not start within", res["message"])

    def test_app_process_map_coverage(self):
        from pc_control.app_launcher import APP_PROCESS_MAP
        self.assertIn("calculator", APP_PROCESS_MAP)
        self.assertIn("CalculatorApp.exe", APP_PROCESS_MAP["calculator"])
        self.assertIn("camera", APP_PROCESS_MAP)
        self.assertIn("WindowsCamera.exe", APP_PROCESS_MAP["camera"])
        self.assertIn("chrome", APP_PROCESS_MAP)
        self.assertIn("vscode", APP_PROCESS_MAP)

if __name__ == "__main__":
    unittest.main()
