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
        cls.client = TestClient(app)

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
