import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import database
import main
from action_policy import action_digest


class AgentTaskPersistenceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.database_patch = patch.object(
            database, "DATABASE_PATH", self.root / "tasks.db"
        )
        self.database_patch.start()
        database.initialize_database()
        main.APPROVALS.clear()
        with database.get_connection() as connection:
            self.conversation_id = connection.execute(
                "INSERT INTO conversations (title) VALUES ('task test')"
            ).lastrowid
        database.create_agent_task(
            "task-test",
            self.conversation_id,
            "Build a small feature",
            str(self.root),
        )

    def tearDown(self):
        main.APPROVALS.clear()
        self.database_patch.stop()
        self.temporary.cleanup()

    def test_persists_task_lifecycle_progress_files_results_and_verification(self):
        database.transition_agent_task("task-test", "planning", "Plan created.")
        database.transition_agent_task("task-test", "inspecting", "Stack inspected.")
        database.transition_agent_task("task-test", "implementing", "Implementing.")
        database.record_agent_task_file_change("task-test", "app.py")
        database.record_agent_task_tool_result(
            "task-test", "write_file", "Applied write to app.py"
        )
        database.transition_agent_task("task-test", "verifying", "Running tests.")
        database.set_agent_task_verification("task-test", "verified")
        database.transition_agent_task("task-test", "completed", "Tests passed.")

        task = database.get_agent_task("task-test")
        self.assertEqual(task["state"], "completed")
        self.assertEqual(task["goal"], "Build a small feature")
        self.assertEqual(task["workspace_path"], str(self.root))
        self.assertEqual(task["changed_files"], ["app.py"])
        self.assertEqual(task["verification_status"], "verified")
        self.assertEqual(task["tool_results"][0]["tool"], "write_file")
        self.assertEqual(
            [entry["state"] for entry in task["progress"] if "state" in entry],
            ["planning", "inspecting", "implementing", "verifying", "completed"],
        )

    def test_rejects_skipped_transitions_and_tracks_cancellation(self):
        with self.assertRaisesRegex(ValueError, "Invalid agent task transition"):
            database.transition_agent_task("task-test", "completed", "Not verified.")
        database.transition_agent_task("task-test", "planning")
        task = database.request_agent_task_cancellation("task-test")
        self.assertTrue(task["cancellation_requested"])
        self.assertTrue(database.agent_task_cancellation_requested("task-test"))
        database.transition_agent_task("task-test", "cancelled", "Cancelled.")
        self.assertEqual(database.get_agent_task("task-test")["state"], "cancelled")
        self.assertTrue(database.request_agent_task_cancellation("task-test")["cancellation_requested"])

    def test_repairing_task_must_transition_via_verifying_before_completion(self):
        database.transition_agent_task("task-test", "planning")
        database.transition_agent_task("task-test", "inspecting")
        database.transition_agent_task("task-test", "implementing")
        database.record_agent_task_file_change("task-test", "app.py")
        database.transition_agent_task("task-test", "verifying", "Running tests.")
        database.set_agent_task_verification("task-test", "failed")
        database.transition_agent_task("task-test", "repairing", "Repairing failed verification.")

        with self.assertRaisesRegex(ValueError, "Invalid agent task transition"):
            database.transition_agent_task("task-test", "completed", "Should not complete from repairing.")

        database.transition_agent_task("task-test", "verifying", "Re-running verification.")
        database.set_agent_task_verification("task-test", "verified")
        database.transition_agent_task("task-test", "completed", "Tests passed.")
        self.assertEqual(database.get_agent_task("task-test")["state"], "completed")
        self.assertEqual(database.get_agent_task("task-test")["verification_status"], "verified")

    async def test_cancel_endpoint_releases_task_approval(self):
        database.transition_agent_task("task-test", "planning")
        arguments = {"command": "npm test"}
        workspace = str(self.root)
        digest = action_digest("run_command", arguments, workspace)
        future = main._register_approval(
            "task-cancel-approval",
            {
                "action": "run_command",
                "arguments": arguments,
                "workspace": workspace,
                "action_digest": digest,
                "risk": "AMBER",
                "target": "npm test",
                "purpose": "Run verification.",
                "reversible": True,
                "alternatives": "Deny.",
                "task_id": "task-test",
            },
        )
        task = await main.cancel_agent_task("task-test")
        self.assertTrue(task["cancellation_requested"])
        self.assertTrue(future.done())
        self.assertFalse(future.result())
        self.assertEqual(main.APPROVALS["task-cancel-approval"].status, "denied")


if __name__ == "__main__":
    unittest.main()
