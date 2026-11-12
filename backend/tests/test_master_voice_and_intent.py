"""
Master Verification Suite for Phase B (Voice Reliability) and Phase C (Unified Tool Orchestration).
Tests the 10 required end-to-end scenarios, entity tracking, pronoun resolution,
multilingual parsing (English, Hindi, Hinglish), clarification, approval workflows, and parity.
"""

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi.testclient import TestClient

import database
from database import initialize_database
from main import app
from core.intent_engine import intent_engine, IntentResult, is_wake_word_present, detect_language
from core.entity_tracker import entity_tracker
from core.tool_registry import tool_registry
from core.engine import kela_engine
from core.conversation_manager import conversation_manager
from core.permission_manager import permission_manager


class MasterVoiceAndIntentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.db_path = Path(cls.temp_dir.name) / "test_master_voice.db"
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
    # 1. Entity Tracker & Pronoun Resolution Unit Tests
    # -------------------------------------------------------------
    def test_entity_tracker_pronoun_resolution_projects(self):
        conv_id = 101
        # Simulate previous turn finding Phone Doctor project
        entity_tracker.update_from_action_result(
            conv_id,
            "search_user_files",
            {"query": "Phone Doctor"},
            {
                "status": "success",
                "results": [
                    {
                        "name": "PhoneDoctor",
                        "path": "C:\\Users\\Kunal Singh\\desktop\\PhoneDoctor",
                        "is_project": True,
                        "type": "directory",
                    }
                ],
            },
        )

        # "Run it" resolves to run project PhoneDoctor
        resolved, meta = entity_tracker.resolve_pronouns("run it", conv_id)
        self.assertTrue(meta["resolved"])
        self.assertEqual(meta["target_type"], "project")
        self.assertEqual(resolved, "run project PhoneDoctor")

        # Hinglish "ise chalao" resolves to run project PhoneDoctor
        resolved_hi, meta_hi = entity_tracker.resolve_pronouns("ise chalao", conv_id)
        self.assertTrue(meta_hi["resolved"])
        self.assertEqual(resolved_hi, "run project PhoneDoctor")

    def test_entity_tracker_pronoun_resolution_files(self):
        conv_id = 102
        entity_tracker.update_from_action_result(
            conv_id,
            "find_resume_files",
            {},
            [{"name": "resume.pdf", "path": "C:\\Users\\Kunal Singh\\Documents\\resume.pdf"}],
        )

        # "Open it" resolves to open file
        resolved, meta = entity_tracker.resolve_pronouns("open it", conv_id)
        self.assertTrue(meta["resolved"])
        self.assertEqual(meta["target_type"], "file")
        self.assertIn("resume.pdf", resolved)

        # Hinglish "kholo ise" resolves to open file
        resolved_hi, meta_hi = entity_tracker.resolve_pronouns("kholo ise", conv_id)
        self.assertTrue(meta_hi["resolved"])
        self.assertEqual(meta_hi["target_type"], "file")

    def test_entity_tracker_pronoun_resolution_apps(self):
        conv_id = 103
        entity_tracker.update_from_action_result(
            conv_id,
            "launch_app",
            {"app_name": "camera"},
            {"status": "success"},
        )

        # "Close it" resolves to close camera
        resolved, meta = entity_tracker.resolve_pronouns("close it", conv_id)
        self.assertTrue(meta["resolved"])
        self.assertEqual(meta["target_type"], "app")
        self.assertEqual(resolved, "close camera")

    # -------------------------------------------------------------
    # 2. Intent Engine: 10 Required Master Mission Scenarios
    # -------------------------------------------------------------
    def test_intent_engine_scenario_1_open_calculator(self):
        # Scenario 1: "Open Calculator."
        r = intent_engine.classify_intent("Open Calculator.")
        self.assertEqual(r.intent_type, "ACTION")
        self.assertEqual(r.tool_name, "launch_app")
        self.assertEqual(r.parameters.get("app_name"), "calculator")

    def test_intent_engine_scenario_2_launch_camera(self):
        # Scenario 2: "Can you launch my camera?"
        r = intent_engine.classify_intent("Can you launch my camera?")
        self.assertEqual(r.intent_type, "ACTION")
        self.assertEqual(r.tool_name, "launch_app")
        self.assertEqual(r.parameters.get("app_name"), "camera")

    def test_intent_engine_scenario_3_find_phone_doctor(self):
        # Scenario 3: "Find my Phone Doctor project."
        r = intent_engine.classify_intent("Find my Phone Doctor project.")
        self.assertEqual(r.intent_type, "ACTION")
        self.assertEqual(r.tool_name, "search_user_files")
        self.assertIn("Phone Doctor", r.parameters.get("query", ""))

    def test_intent_engine_scenario_4_where_is_resume(self):
        # Scenario 4: "Where is my resume?"
        r = intent_engine.classify_intent("Where is my resume?")
        self.assertEqual(r.intent_type, "ACTION")
        self.assertEqual(r.tool_name, "find_resume_files")

    def test_intent_engine_scenario_5_ram_usage(self):
        # Scenario 5: "What is my laptop's RAM usage?"
        r = intent_engine.classify_intent("What is my laptop's RAM usage?")
        self.assertEqual(r.intent_type, "ACTION")
        self.assertEqual(r.tool_name, "get_system_metrics")

    def test_intent_engine_scenario_6_who_am_i(self):
        # Scenario 6: "Who am I?"
        r = intent_engine.classify_intent("Who am I?")
        self.assertEqual(r.intent_type, "QUESTION")
        self.assertIn("Kunal Singh", r.response_text)
        self.assertIn("Nexus AI", r.response_text)

    def test_intent_engine_scenario_7_tell_me_more(self):
        # Scenario 7: "Tell me more."
        r = intent_engine.classify_intent("Tell me more.")
        self.assertEqual(r.intent_type, "QUESTION")
        self.assertTrue(r.is_followup)

    def test_intent_engine_scenario_8_run_it_pronoun(self):
        # Scenario 8: "Run it" after identifying Phone Doctor
        conv_id = 108
        entity_tracker.update_entities(
            conv_id,
            last_project={"name": "Phone Doctor", "path": "C:\\desktop\\PhoneDoctor"},
        )
        r = intent_engine.classify_intent("Run it", conversation_id=conv_id)
        self.assertEqual(r.intent_type, "ACTION")
        self.assertEqual(r.tool_name, "run_project")
        self.assertEqual(r.parameters.get("project_name"), "Phone Doctor")

    def test_intent_engine_scenario_9_unsupported_command(self):
        # Scenario 9: Unsupported command ("Order a pizza for me")
        r = intent_engine.classify_intent("Order a pizza for me")
        self.assertEqual(r.intent_type, "UNSUPPORTED")
        self.assertIsNotNone(r.unsupported_reason)
        self.assertIn("cannot", r.response_text.lower())
        self.assertFalse(r.response_text == "")

    def test_intent_engine_scenario_10_ambiguous_request(self):
        # Scenario 10: Ambiguous request ("Delete it" with no context)
        r = intent_engine.classify_intent("Delete it")
        self.assertEqual(r.intent_type, "CLARIFICATION_NEEDED")
        self.assertIsNotNone(r.clarification_question)
        self.assertIn("?", r.clarification_question)

    # -------------------------------------------------------------
    # 3. Multilingual Support: Hindi and Hinglish
    # -------------------------------------------------------------
    def test_multilingual_detection_and_classification(self):
        # Camera
        r_cam = intent_engine.classify_intent("camera kholo")
        self.assertEqual(r_cam.intent_type, "ACTION")
        self.assertEqual(r_cam.tool_name, "launch_app")
        self.assertEqual(r_cam.parameters["app_name"], "camera")
        self.assertEqual(r_cam.language, "hinglish")

        # Calculator
        r_calc = intent_engine.classify_intent("calculator chalao")
        self.assertEqual(r_calc.intent_type, "ACTION")
        self.assertEqual(r_calc.tool_name, "launch_app")
        self.assertEqual(r_calc.parameters["app_name"], "calculator")
        self.assertEqual(r_calc.language, "hinglish")

        # Volume
        r_vol = intent_engine.classify_intent("awaz badhao")
        self.assertEqual(r_vol.intent_type, "ACTION")
        self.assertEqual(r_vol.tool_name, "change_volume")
        self.assertEqual(r_vol.language, "hinglish")

        # RAM
        r_ram = intent_engine.classify_intent("pc ka ram kitna use ho raha hai")
        self.assertEqual(r_ram.intent_type, "ACTION")
        self.assertEqual(r_ram.tool_name, "get_system_metrics")
        self.assertEqual(r_ram.language, "hinglish")

        # Identity
        r_who = intent_engine.classify_intent("tum kaun ho")
        self.assertEqual(r_who.intent_type, "QUESTION")
        self.assertEqual(r_who.language, "hinglish")
        self.assertIn("Main KELA hoon", r_who.response_text)

    # -------------------------------------------------------------
    # 4. Tool Registry Schemas and Risk Levels
    # -------------------------------------------------------------
    def test_tool_registry_schemas_and_risk(self):
        # Verify PC tools exist in schemas
        schemas = {s["name"]: s for s in tool_registry.list_schemas()}
        self.assertIn("launch_app", schemas)
        self.assertIn("close_app", schemas)
        self.assertIn("get_system_metrics", schemas)
        self.assertIn("search_user_files", schemas)
        self.assertIn("find_resume_files", schemas)
        self.assertIn("run_project", schemas)

        # Risk classification
        self.assertEqual(tool_registry.get_tool_risk("launch_app"), "GREEN")
        self.assertEqual(tool_registry.get_tool_risk("get_system_metrics"), "GREEN")
        self.assertEqual(tool_registry.get_tool_risk("search_user_files"), "GREEN")
        self.assertEqual(tool_registry.get_tool_risk("run_project"), "AMBER")
        self.assertEqual(tool_registry.get_tool_risk("format_drive"), "RED")

    # -------------------------------------------------------------
    # 5. Spoken Response Formatting
    # -------------------------------------------------------------
    def test_spoken_response_formatting(self):
        # English RAM formatting
        intent_ram = IntentResult(intent_type="ACTION", tool_name="get_system_metrics")
        metrics_mock = {
            "status": "success",
            "result": {
                "metrics": {
                    "ram_usage_percent": 45,
                    "used_ram_mb": 7372,
                    "total_ram_mb": 16384,
                    "battery_percent": 92,
                }
            },
        }
        resp_en = intent_engine.format_action_response(intent_ram, metrics_mock, lang="english")
        self.assertIn("45%", resp_en)
        self.assertIn("RAM usage", resp_en)

        # Hinglish RAM formatting
        resp_hi = intent_engine.format_action_response(intent_ram, metrics_mock, lang="hinglish")
        self.assertIn("45%", resp_hi)
        self.assertIn("Aapke laptop ka RAM usage", resp_hi)

    # -------------------------------------------------------------
    # 6. End-to-End Voice API Endpoint Scenarios
    # -------------------------------------------------------------
    def test_voice_endpoint_end_to_end_scenarios(self):
        # Create persistent session
        conv = conversation_manager.create_conversation(title="E2E Voice Master Test")
        conv_id = conv["id"]

        # Turn 1: RAM Usage
        resp1 = self.client.post(
            "/api/voice/conversation",
            json={"text": "What is my laptop's RAM usage?", "conversation_id": conv_id, "turn_id": "e2e_turn_1"},
        )
        self.assertEqual(resp1.status_code, 200)
        d1 = resp1.json()
        self.assertTrue(d1["handled"])
        self.assertIn("RAM usage", d1["response_text"])
        self.assertEqual(d1["conversation_id"], conv_id)

        # Turn 2: Find Phone Doctor project
        resp2 = self.client.post(
            "/api/voice/conversation",
            json={"text": "Find my Phone Doctor project.", "conversation_id": conv_id, "turn_id": "e2e_turn_2"},
        )
        self.assertEqual(resp2.status_code, 200)
        d2 = resp2.json()
        self.assertTrue(d2["handled"])
        self.assertTrue(
            "phone-doctor" in d2["response_text"].lower()
            or "phonedoctor" in d2["response_text"].lower()
            or "phone doctor" in d2["response_text"].lower()
        )

        # Turn 3: "Run it" (pronoun resolution across turns!)
        resp3 = self.client.post(
            "/api/voice/conversation",
            json={"text": "Run it", "conversation_id": conv_id, "turn_id": "e2e_turn_3"},
        )
        self.assertEqual(resp3.status_code, 200)
        d3 = resp3.json()
        # AMBER risk: requires approval, responds with approval instruction
        self.assertTrue(d3.get("requires_approval", False) or "approval" in d3["response_text"].lower())
        self.assertTrue(
            "phone-doctor" in d3["response_text"].lower()
            or "phonedoctor" in d3["response_text"].lower()
            or "phone doctor" in d3["response_text"].lower()
        )

        # Turn 4: Unsupported command
        resp4 = self.client.post(
            "/api/voice/conversation",
            json={"text": "Order a pizza for me", "conversation_id": conv_id, "turn_id": "e2e_turn_4"},
        )
        self.assertEqual(resp4.status_code, 200)
        d4 = resp4.json()
        self.assertTrue(d4["handled"])
        self.assertIn("cannot", d4["response_text"].lower())

        # Turn 5: Ambiguous command
        resp5 = self.client.post(
            "/api/voice/conversation",
            json={"text": "Delete it", "conversation_id": conv_id, "turn_id": "e2e_turn_5"},
        )
        self.assertEqual(resp5.status_code, 200)
        d5 = resp5.json()
        self.assertTrue(d5["handled"])
        self.assertTrue(d5.get("clarification_needed", False) or "?" in d5["response_text"])

        # Verify all turns persisted to SQLite
        messages = conversation_manager.get_messages(conv_id)
        self.assertEqual(len(messages), 10)  # 5 user turns + 5 assistant turns

    # -------------------------------------------------------------
    # 7. Text Chat Stream Parity
    # -------------------------------------------------------------
    def test_text_chat_stream_parity_executes_action(self):
        conv = conversation_manager.create_conversation(title="Text Parity Test")
        conv_id = conv["id"]

        async def _run_stream():
            tokens = []
            steps = []
            async for chunk in kela_engine.chat_stream(
                messages=[{"role": "user", "content": "What is my laptop's RAM usage?"}],
                conversation_id=conv_id,
                turn_id="text_parity_turn_1",
            ):
                import json
                parsed = json.loads(chunk.strip())
                if "token" in parsed:
                    tokens.append(parsed["token"])
                if "step" in parsed:
                    steps.append(parsed["step"])
            return steps, "".join(tokens)

        steps, output_text = asyncio.run(_run_stream())
        self.assertTrue(any("Executing tool" in s for s in steps))
        self.assertIn("RAM usage", output_text)

        # Check SQLite persistence
        msgs = conversation_manager.get_messages(conv_id)
        self.assertEqual(len(msgs), 2)
        self.assertEqual(msgs[0]["content"], "What is my laptop's RAM usage?")
        self.assertIn("RAM usage", msgs[1]["content"])


if __name__ == "__main__":
    unittest.main()
