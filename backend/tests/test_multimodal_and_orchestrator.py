import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from browser.engine import SimpleDOMParser
import database
from database import initialize_database
from documents.processor import extract_pdf_pages, process_document
from image_gen.generator import ImageGenerationAgent, generate_procedural_svg
from orchestrator.router import (
    AutonomyLevel,
    Orchestrator,
    TaskCategory,
    classify_task_intent,
    get_current_autonomy_level,
    set_current_autonomy_level,
)
from vision.analyzer import VisionAgent, inspect_image_header


class MultimodalAndOrchestratorTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.db_path = Path(cls.temp_dir.name) / "test_multi.db"
        cls.db_patch = patch.object(database, "DATABASE_PATH", cls.db_path)
        cls.db_patch.start()
        initialize_database()

    @classmethod
    def tearDownClass(cls):
        cls.db_patch.stop()
        cls.temp_dir.cleanup()

    def test_document_processor_csv_and_text(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            csv_path = Path(tmp_dir) / "metrics.csv"
            csv_path.write_text("metric,value,unit\nlatency,45,ms\nthroughput,1200,rps\n", encoding="utf-8")

            res_csv = process_document(csv_path)
            self.assertEqual(res_csv["document_type"], "csv")
            self.assertEqual(res_csv["row_count"], 2)
            self.assertIn("| latency | 45 | ms |", res_csv["content"])

            txt_path = Path(tmp_dir) / "notes.txt"
            txt_path.write_text("Autonomous AI Operating System Notes", encoding="utf-8")
            res_txt = process_document(txt_path)
            self.assertEqual(res_txt["document_type"], "text")
            self.assertIn("Autonomous AI Operating System Notes", res_txt["content"])

    def test_pdf_page_extractor_and_citations(self):
        # Synthetic mock PDF bytes with stream
        pdf_bytes = b"%PDF-1.4\n1 0 obj\n<< /Length 20 >>\nstream\n(Hello Nexus AI) Tj\nendstream\nendobj\n%%EOF"
        pages = extract_pdf_pages(pdf_bytes)
        self.assertGreater(len(pages), 0)
        self.assertEqual(pages[0]["citation"], "[Page 1]")
        self.assertIn("Hello Nexus AI", pages[0]["text"])

    def test_image_header_inspector_png(self):
        # Construct valid 16x16 PNG header
        # \x89PNG\r\n\x1a\n + IHDR chunk with width=16, height=16
        png_header = (
            b"\x89PNG\r\n\x1a\n"
            b"\x00\x00\x00\rIHDR"
            b"\x00\x00\x00\x10"  # width 16
            b"\x00\x00\x00\x10"  # height 16
            b"\x08\x06\x00\x00\x00"
            b"\x00\x00\x00\x00"
        )
        meta = inspect_image_header(png_header)
        self.assertEqual(meta["format"], "PNG")
        self.assertEqual(meta["width"], 16)
        self.assertEqual(meta["height"], 16)

    def test_procedural_svg_generator(self):
        svg = generate_procedural_svg("Deep neural network architecture diagram", width=800, height=600)
        self.assertTrue(svg.startswith("<svg"))
        self.assertTrue(svg.endswith("</svg>"))
        self.assertIn("viewBox=\"0 0 800 600\"", svg)
        self.assertIn("CORE", svg)
        self.assertIn("NEXUS AI GENERATIVE STUDIO", svg)

    def test_image_generation_agent_gallery(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            agent = ImageGenerationAgent(workspace_path=tmp_dir)
            self.assertEqual(len(agent.list_gallery()), 0)

            # Generate SVG image
            res = generate_procedural_svg("Test icon")
            target = agent.gallery_dir / "test.svg"
            target.write_text(res, encoding="utf-8")

            record = {
                "id": "img_123",
                "filename": "test.svg",
                "file_path": str(target),
                "format": "SVG",
                "prompt": "Test icon",
                "width": 800,
                "height": 600,
                "created_at": "2026-11-01T00:00:00",
            }
            agent._save_manifest([record])

            gallery = agent.list_gallery()
            self.assertEqual(len(gallery), 1)
            self.assertEqual(gallery[0]["id"], "img_123")

            # Delete
            deleted = agent.delete_image("img_123")
            self.assertTrue(deleted)
            self.assertEqual(len(agent.list_gallery()), 0)

    def test_simple_dom_parser(self):
        html = """
        <!DOCTYPE html>
        <html>
          <head>
            <title>Nexus AI Operating System</title>
            <meta name="description" content="Personal autonomous AI assistant" />
          </head>
          <body>
            <h1>Welcome to Nexus</h1>
            <p>Nexus is built for deep reasoning and execution.</p>
            <a href="/docs/api">API Documentation</a>
            <form action="/login" method="POST">
              <input type="text" name="username" placeholder="Username" />
              <input type="password" name="password" />
            </form>
          </body>
        </html>
        """
        parser = SimpleDOMParser("https://nexus.ai")
        parser.feed(html)

        self.assertEqual(parser.title.strip(), "Nexus AI Operating System")
        self.assertEqual(parser.meta_description, "Personal autonomous AI assistant")
        self.assertEqual(len(parser.links), 1)
        self.assertEqual(parser.links[0]["href"], "https://nexus.ai/docs/api")
        self.assertEqual(len(parser.forms), 1)
        self.assertEqual(parser.forms[0]["method"], "POST")
        self.assertEqual(len(parser.forms[0]["inputs"]), 2)

    def test_task_intent_classification(self):
        self.assertEqual(classify_task_intent("Inspect my CareCompass repository and fix tests"), TaskCategory.GITHUB)
        self.assertEqual(classify_task_intent("Fix the login bug in auth.py and verify tests"), TaskCategory.CODING)
        self.assertEqual(classify_task_intent("Generate an image of a futuristic neural processor"), TaskCategory.IMAGE_GEN)
        self.assertEqual(classify_task_intent("Open this website https://fastapi.tiangolo.com and read it"), TaskCategory.BROWSER)
        self.assertEqual(classify_task_intent("Run SQL query against sqlite database users table"), TaskCategory.DATABASE)
        self.assertEqual(classify_task_intent("Deep research into quantum machine learning architectures"), TaskCategory.RESEARCH)
        self.assertEqual(classify_task_intent("Analyze this image", has_image=True), TaskCategory.VISION)
        self.assertEqual(classify_task_intent("Analyse this PDF report", has_document=True), TaskCategory.DOCUMENT)
        self.assertEqual(classify_task_intent("Hello, how are you today?"), TaskCategory.GENERAL_CHAT)

    def test_autonomy_level_management(self):
        self.assertEqual(get_current_autonomy_level(), AutonomyLevel.LEVEL_3_ASSISTED.value)
        set_current_autonomy_level(4)
        self.assertEqual(get_current_autonomy_level(), 4)
        set_current_autonomy_level(3)
        self.assertEqual(get_current_autonomy_level(), 3)

    async def test_orchestrator_planning_and_streaming(self):
        orchestrator = Orchestrator(".")
        plan = orchestrator.create_plan(
            query="Inspect my GitHub repository, fix tests and commit changes",
            category=TaskCategory.GITHUB,
            autonomy_level=3,
        )
        self.assertEqual(plan["category"], "github")
        self.assertGreater(plan["total_steps"], 3)
        self.assertEqual(plan["steps"][0]["agent"], "GitHub Agent")

        # Stream execution
        events = []
        async for line in orchestrator.execute_orchestrated_stream(
            query="Inspect my GitHub repository",
            category=TaskCategory.GITHUB,
            autonomy_level=3,
            conversation_id=1,
            turn_id="turn-orch-1",
        ):
            if line.strip():
                events.append(json.loads(line))

        event_types = [e.get("type") for e in events if "type" in e]
        self.assertIn("orchestrator_plan", event_types)
        self.assertIn("orchestrator_step", event_types)
        has_done = any(e.get("done") for e in events)
        self.assertTrue(has_done)


if __name__ == "__main__":
    unittest.main()
