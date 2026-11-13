"""
Comprehensive Test Suite for KELA Browser and Web Launching Pipeline.
Covers 16 critical verification scenarios:
1. Open YouTube
2. Open Google
3. Open GitHub
4. Open arbitrary HTTPS URL
5. Open URL without explicit scheme (e.g. reddit.com)
6. Open Edge
7. Open Brave
8. Requested browser not installed (Chrome)
9. Default browser fallback
10. Google search request
11. YouTube search request
12. Invalid URL
13. Windows launch failure (mock win32_shell_execute <= 32)
14. No false success after launch failure
15. Hindi and Hinglish commands
16. Voice and text tool parity
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from pc_control.app_launcher import (
    launch_browser,
    open_youtube,
    search_web_in_browser,
    normalize_web_destination,
    find_installed_browsers,
    WIN32_ERROR_MESSAGES,
)
from core.intent_engine import intent_engine, IntentResult
from core.tool_registry import tool_registry
from core.entity_tracker import entity_tracker


class BrowserAndWebTests(unittest.TestCase):
    """Rigorous tests for browser and website launching across KELA."""

    def setUp(self):
        # Reset entity tracker for clean isolation
        self.conv_id = 999
        entity_tracker.clear_context(self.conv_id)

    # -------------------------------------------------------------
    # Scenario 1: Open YouTube
    # -------------------------------------------------------------
    @patch("pc_control.app_launcher.win32_shell_execute", return_value=42)
    def test_scenario_01_open_youtube(self, mock_shell):
        intent = intent_engine.classify_intent("Open YouTube.")
        self.assertEqual(intent.intent_type, "ACTION")
        self.assertIn(intent.tool_name, {"open_youtube", "launch_browser"})
        self.assertIn("youtube.com", intent.parameters.get("url", ""))

        result = tool_registry.execute_tool(intent.tool_name, intent.parameters)
        self.assertEqual(result["status"], "success")
        res_data = result["result"]
        self.assertTrue(res_data["verified"])
        self.assertGreater(res_data["launch_code"], 32)

        resp = intent_engine.format_action_response(intent, result, lang="english")
        self.assertIn("YouTube", resp)
        self.assertIn("Opened", resp)

    # -------------------------------------------------------------
    # Scenario 2: Open Google
    # -------------------------------------------------------------
    @patch("pc_control.app_launcher.win32_shell_execute", return_value=42)
    def test_scenario_02_open_google(self, mock_shell):
        intent = intent_engine.classify_intent("Open Google.")
        self.assertEqual(intent.intent_type, "ACTION")
        self.assertEqual(intent.tool_name, "launch_browser")
        self.assertEqual(intent.parameters.get("requested_destination"), "google")
        self.assertEqual(intent.parameters.get("url"), "https://www.google.com")

        result = tool_registry.execute_tool("launch_browser", intent.parameters)
        self.assertEqual(result["status"], "success")
        self.assertTrue(result["result"]["verified"])
        self.assertGreater(result["result"]["launch_code"], 32)

        resp = intent_engine.format_action_response(intent, result, lang="english")
        self.assertIn("Google", resp)
        self.assertIn("Opened", resp)

    # -------------------------------------------------------------
    # Scenario 3: Open GitHub
    # -------------------------------------------------------------
    @patch("pc_control.app_launcher.win32_shell_execute", return_value=42)
    def test_scenario_03_open_github(self, mock_shell):
        intent = intent_engine.classify_intent("Open GitHub.")
        self.assertEqual(intent.intent_type, "ACTION")
        self.assertEqual(intent.tool_name, "launch_browser")
        self.assertEqual(intent.parameters.get("requested_destination"), "github")
        self.assertEqual(intent.parameters.get("url"), "https://github.com")

        result = tool_registry.execute_tool("launch_browser", intent.parameters)
        self.assertEqual(result["status"], "success")
        self.assertTrue(result["result"]["verified"])

        resp = intent_engine.format_action_response(intent, result, lang="english")
        self.assertIn("GitHub", resp)
        self.assertIn("Opened", resp)

    # -------------------------------------------------------------
    # Scenario 4: Open arbitrary HTTPS URL
    # -------------------------------------------------------------
    @patch("pc_control.app_launcher.win32_shell_execute", return_value=42)
    def test_scenario_04_open_arbitrary_https_url(self, mock_shell):
        test_url = "https://github.com/torvalds/linux"
        intent = intent_engine.classify_intent(f"Open {test_url}")
        self.assertEqual(intent.intent_type, "ACTION")
        self.assertEqual(intent.tool_name, "launch_browser")
        self.assertEqual(intent.parameters.get("url"), test_url)

        result = tool_registry.execute_tool("launch_browser", intent.parameters)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["result"]["resolved_url"], test_url)

    # -------------------------------------------------------------
    # Scenario 5: Open URL without explicit scheme (e.g. reddit.com)
    # -------------------------------------------------------------
    @patch("pc_control.app_launcher.win32_shell_execute", return_value=42)
    def test_scenario_05_open_url_without_scheme(self, mock_shell):
        norm = normalize_web_destination("reddit.com")
        self.assertEqual(norm, "https://reddit.com")

        intent = intent_engine.classify_intent("Open reddit.com")
        self.assertEqual(intent.intent_type, "ACTION")
        self.assertEqual(intent.tool_name, "launch_browser")
        self.assertEqual(intent.parameters.get("url"), "https://reddit.com")

        result = tool_registry.execute_tool("launch_browser", intent.parameters)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["result"]["resolved_url"], "https://reddit.com")

    # -------------------------------------------------------------
    # Scenario 6: Open Edge
    # -------------------------------------------------------------
    @patch("pc_control.app_launcher.win32_shell_execute", return_value=42)
    def test_scenario_06_open_edge(self, mock_shell):
        intent = intent_engine.classify_intent("Open Microsoft Edge.")
        self.assertEqual(intent.intent_type, "ACTION")
        self.assertEqual(intent.tool_name, "launch_browser")
        self.assertEqual(intent.parameters.get("browser_name"), "edge")

        result = tool_registry.execute_tool("launch_browser", intent.parameters)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["result"]["browser"], "Microsoft Edge")

        resp = intent_engine.format_action_response(intent, result, lang="english")
        self.assertIn("Microsoft Edge", resp)

    # -------------------------------------------------------------
    # Scenario 7: Open Brave
    # -------------------------------------------------------------
    @patch("pc_control.app_launcher.win32_shell_execute", return_value=42)
    def test_scenario_07_open_brave(self, mock_shell):
        intent = intent_engine.classify_intent("Open Brave.")
        self.assertEqual(intent.intent_type, "ACTION")
        self.assertEqual(intent.tool_name, "launch_browser")
        self.assertEqual(intent.parameters.get("browser_name"), "brave")

        result = tool_registry.execute_tool("launch_browser", intent.parameters)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["result"]["browser"], "Brave")

        resp = intent_engine.format_action_response(intent, result, lang="english")
        self.assertIn("Brave", resp)

    # -------------------------------------------------------------
    # Scenario 8: Requested browser not installed (Chrome)
    # -------------------------------------------------------------
    @patch("pc_control.app_launcher.find_chrome_executable", return_value=None)
    def test_scenario_08_requested_browser_not_installed(self, mock_chrome):
        intent = intent_engine.classify_intent("Open Chrome.")
        self.assertEqual(intent.intent_type, "ACTION")
        self.assertEqual(intent.parameters.get("browser_name"), "chrome")

        result = tool_registry.execute_tool("launch_browser", intent.parameters)
        self.assertEqual(result["status"], "error")
        res_data = result["result"]
        self.assertFalse(res_data["verified"])
        self.assertIn("not installed", res_data["error"])

        resp = intent_engine.format_action_response(intent, result, lang="english")
        self.assertIn("not installed", resp.lower())
        self.assertNotIn("Opened", resp)

    # -------------------------------------------------------------
    # Scenario 9: Default browser fallback
    # -------------------------------------------------------------
    @patch("pc_control.app_launcher.win32_shell_execute", return_value=42)
    def test_scenario_09_default_browser_fallback(self, mock_shell):
        result = launch_browser(browser_name=None, url="https://www.google.com")
        self.assertEqual(result["status"], "success")
        self.assertTrue(result["verified"])
        # Defaults to installed browser (Brave or Edge)
        self.assertIn(result["browser"], {"Brave", "Microsoft Edge"})

    # -------------------------------------------------------------
    # Scenario 10: Google search request
    # -------------------------------------------------------------
    @patch("pc_control.app_launcher.win32_shell_execute", return_value=42)
    def test_scenario_10_google_search_request(self, mock_shell):
        intent = intent_engine.classify_intent("search ai news on google")
        self.assertEqual(intent.intent_type, "ACTION")
        self.assertEqual(intent.tool_name, "search_web_in_browser")
        self.assertEqual(intent.parameters.get("engine"), "google")
        self.assertEqual(intent.parameters.get("query"), "ai news")

        result = tool_registry.execute_tool("search_web_in_browser", intent.parameters)
        self.assertEqual(result["status"], "success")
        self.assertTrue(result["result"]["verified"])
        self.assertIn("google.com/search", result["result"]["search_url"])

        resp = intent_engine.format_action_response(intent, result, lang="english")
        self.assertIn("ai news", resp)
        self.assertIn("Google", resp)

    # -------------------------------------------------------------
    # Scenario 11: YouTube search request
    # -------------------------------------------------------------
    @patch("pc_control.app_launcher.win32_shell_execute", return_value=42)
    def test_scenario_11_youtube_search_request(self, mock_shell):
        intent = intent_engine.classify_intent("search for python tutorials on youtube")
        self.assertEqual(intent.intent_type, "ACTION")
        self.assertEqual(intent.tool_name, "search_web_in_browser")
        self.assertEqual(intent.parameters.get("engine"), "youtube")
        self.assertEqual(intent.parameters.get("query"), "python tutorials")

        result = tool_registry.execute_tool("search_web_in_browser", intent.parameters)
        self.assertEqual(result["status"], "success")
        self.assertTrue(result["result"]["verified"])
        self.assertIn("youtube.com/results", result["result"]["search_url"])

        resp = intent_engine.format_action_response(intent, result, lang="english")
        self.assertIn("python tutorials", resp)
        self.assertIn("YouTube", resp)

    # -------------------------------------------------------------
    # Scenario 12: Invalid URL
    # -------------------------------------------------------------
    def test_scenario_12_invalid_url(self):
        norm = normalize_web_destination("invalid::url::format")
        self.assertIsNone(norm)

        result = launch_browser(url="http://")
        self.assertEqual(result["status"], "error")
        self.assertFalse(result["verified"])
        self.assertIn("Invalid URL format", result["error"])

    # -------------------------------------------------------------
    # Scenario 13: Windows launch failure (mock win32_shell_execute <= 32)
    # -------------------------------------------------------------
    @patch("pc_control.app_launcher.win32_shell_execute", return_value=2)
    def test_scenario_13_windows_launch_failure(self, mock_shell):
        result = launch_browser(url="https://www.example.com")
        self.assertEqual(result["status"], "error")
        self.assertFalse(result["verified"])
        self.assertEqual(result["error_code"], 2)
        self.assertIn("not found", result["error"].lower())

    # -------------------------------------------------------------
    # Scenario 14: No false success after launch failure
    # -------------------------------------------------------------
    @patch("pc_control.app_launcher.win32_shell_execute", return_value=5)  # Access Denied
    def test_scenario_14_no_false_success_after_failure(self, mock_shell):
        intent = IntentResult(
            intent_type="ACTION",
            tool_name="launch_browser",
            parameters={"url": "https://www.google.com", "requested_destination": "google"},
        )
        fail_result = tool_registry.execute_tool("launch_browser", intent.parameters)
        self.assertEqual(fail_result["status"], "error")
        self.assertFalse(fail_result["result"]["verified"])

        resp = intent_engine.format_action_response(intent, fail_result, lang="english")
        self.assertNotIn("Opened", resp)
        self.assertNotIn("Success", resp)
        self.assertIn("Access was denied", resp)

    # -------------------------------------------------------------
    # Scenario 15: Hindi and Hinglish commands
    # -------------------------------------------------------------
    @patch("pc_control.app_launcher.win32_shell_execute", return_value=42)
    def test_scenario_15_hindi_and_hinglish_commands(self, mock_shell):
        # 15a: "Google khol do"
        intent_hi1 = intent_engine.classify_intent("Google khol do")
        self.assertEqual(intent_hi1.intent_type, "ACTION")
        self.assertEqual(intent_hi1.tool_name, "launch_browser")
        self.assertEqual(intent_hi1.language, "hinglish")

        res_hi1 = tool_registry.execute_tool("launch_browser", intent_hi1.parameters)
        resp_hi1 = intent_engine.format_action_response(intent_hi1, res_hi1, lang="hinglish")
        self.assertIn("Google khol diya hai", resp_hi1)

        # 15b: "GitHub kholo"
        intent_hi2 = intent_engine.classify_intent("GitHub kholo")
        self.assertEqual(intent_hi2.intent_type, "ACTION")
        self.assertEqual(intent_hi2.tool_name, "launch_browser")

        # 15c: "Brave mein YouTube kholo"
        intent_hi3 = intent_engine.classify_intent("Brave mein YouTube kholo")
        self.assertEqual(intent_hi3.intent_type, "ACTION")
        self.assertEqual(intent_hi3.parameters.get("browser_name"), "brave")
        self.assertIn("youtube.com", intent_hi3.parameters.get("url", ""))

        # 15d: "youtube par python tutorial dhundo"
        intent_hi4 = intent_engine.classify_intent("youtube par python tutorial dhundo")
        self.assertEqual(intent_hi4.intent_type, "ACTION")
        self.assertEqual(intent_hi4.tool_name, "search_web_in_browser")
        self.assertEqual(intent_hi4.parameters.get("engine"), "youtube")
        self.assertEqual(intent_hi4.parameters.get("query"), "python tutorial")

    # -------------------------------------------------------------
    # Scenario 16: Voice and text tool parity
    # -------------------------------------------------------------
    @patch("pc_control.app_launcher.win32_shell_execute", return_value=42)
    def test_scenario_16_voice_and_text_tool_parity(self, mock_shell):
        from voice.router import resolve_voice_intent

        command = "Open Google."

        # Text classification
        text_intent = intent_engine.classify_intent(command)
        # Voice resolution
        voice_res = resolve_voice_intent(command)

        self.assertEqual(text_intent.intent_type, "ACTION")
        self.assertEqual(voice_res["intent_type"], "ACTION")
        self.assertEqual(text_intent.tool_name, voice_res["action"])
        self.assertEqual(text_intent.parameters.get("url"), voice_res["params"].get("url"))

        # Both route through tool_registry
        text_exec = tool_registry.execute_tool(text_intent.tool_name, text_intent.parameters)
        voice_exec = tool_registry.execute_tool(voice_res["action"], voice_res["params"])

        self.assertEqual(text_exec["status"], "success")
        self.assertEqual(voice_exec["status"], "success")
        self.assertEqual(text_exec["result"]["browser"], voice_exec["result"]["browser"])
        self.assertEqual(text_exec["result"]["launch_code"], voice_exec["result"]["launch_code"])


if __name__ == "__main__":
    unittest.main()
