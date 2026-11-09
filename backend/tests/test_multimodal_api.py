import base64
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

import database
from database import initialize_database
from main import app


class MultimodalApiRoutesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.db_path = Path(cls.temp_dir.name) / "test_api.db"
        cls.db_patch = patch.object(database, "DATABASE_PATH", cls.db_path)
        cls.db_patch.start()
        initialize_database()
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        cls.db_patch.stop()
        cls.temp_dir.cleanup()

    def test_orchestrator_autonomy_routes(self):
        # 1. Get current autonomy level
        res = self.client.get("/api/orchestrator/autonomy")
        self.assertEqual(res.status_code, 200)
        self.assertIn("level", res.json())

        # 2. Set autonomy level to 4
        res_set = self.client.post("/api/orchestrator/autonomy", json={"level": 4})
        self.assertEqual(res_set.status_code, 200)
        self.assertEqual(res_set.json()["level"], 4)

        # 3. Verify get reflects change
        res_check = self.client.get("/api/orchestrator/autonomy")
        self.assertEqual(res_check.json()["level"], 4)

        # Restore to 3
        self.client.post("/api/orchestrator/autonomy", json={"level": 3})

    def test_orchestrator_plan_route(self):
        payload = {
            "query": "Inspect my GitHub repository, fix tests and commit changes",
        }
        res = self.client.post("/api/orchestrator/plan", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["category"], "github")
        self.assertGreater(data["total_steps"], 0)
        self.assertTrue(any("GitHub" in s["agent"] for s in data["steps"]))

    def test_github_status_route(self):
        res = self.client.get("/api/github/status")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("github_auth", data)
        self.assertIn("workspace_git", data)

    def test_vision_models_route(self):
        res = self.client.get("/api/vision/models")
        self.assertEqual(res.status_code, 200)
        self.assertIn("models", res.json())

    def test_image_generation_and_gallery_routes(self):
        # 1. Backends check
        res_be = self.client.get("/api/image-gen/backends")
        self.assertEqual(res_be.status_code, 200)
        self.assertIn("procedural_vector", res_be.json())

        # 2. Generate procedural image
        res_gen = self.client.post(
            "/api/image-gen/generate",
            json={"prompt": "System architecture flowchart", "width": 800, "height": 600},
        )
        self.assertEqual(res_gen.status_code, 200)
        data = res_gen.json()
        self.assertTrue(data["success"])
        img_id = data["image"]["id"]

        # 3. Gallery list contains new image
        res_gal = self.client.get("/api/image-gen/gallery")
        self.assertEqual(res_gal.status_code, 200)
        items = res_gal.json()
        self.assertTrue(any(i["id"] == img_id for i in items))

        # 4. Delete image
        res_del = self.client.delete(f"/api/image-gen/gallery/{img_id}")
        self.assertEqual(res_del.status_code, 200)
        self.assertTrue(res_del.json()["deleted"])

    def test_document_processor_route(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc_file = Path(tmp) / "summary.txt"
            doc_file.write_text("Autonomous Personal AI System Blueprint", encoding="utf-8")

            res = self.client.post(
                "/api/documents/process",
                json={"file_path": str(doc_file)},
            )
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertEqual(data["document_type"], "text")
            self.assertIn("Autonomous Personal AI System Blueprint", data["content"])


if __name__ == "__main__":
    unittest.main()
