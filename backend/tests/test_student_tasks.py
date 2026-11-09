import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import database
import main
from fastapi.testclient import TestClient


class StudentTaskManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.database_patch = patch.object(database, "DATABASE_PATH", self.root / "student_tasks.db")
        self.database_patch.start()
        database.initialize_database()
        self.client = TestClient(main.app)

    def tearDown(self):
        self.client.close()
        self.database_patch.stop()
        self.temp_dir.cleanup()

    def test_student_tasks_can_be_created_listed_and_completed(self):
        create_response = self.client.post(
            "/api/student/tasks",
            json={"title": "Write algebra review"},
        )
        self.assertEqual(create_response.status_code, 200)
        created = create_response.json()["task"]
        self.assertEqual(created["title"], "Write algebra review")
        self.assertEqual(created["completed"], 0)

        list_response = self.client.get("/api/student/tasks")
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(len(list_response.json()["tasks"]), 1)

        update_response = self.client.patch(
            f"/api/student/tasks/{created['id']}",
            json={"completed": True},
        )
        self.assertEqual(update_response.status_code, 200)
        updated = update_response.json()["task"]
        self.assertEqual(updated["completed"], 1)

    def test_student_tasks_reject_blank_titles(self):
        response = self.client.post("/api/student/tasks", json={"title": "   "})
        self.assertEqual(response.status_code, 400)
        self.assertIn("Task title is required", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
