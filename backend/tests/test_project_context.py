import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import database
import main


class ProjectContextTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.database_patch = patch.object(
            database, "DATABASE_PATH", self.root / "test.db"
        )
        self.database_patch.start()
        database.initialize_database()
        self.previous_workspace = getattr(main.app.state, "workspace", None)
        main.app.state.workspace = self.root

    async def asyncTearDown(self):
        if self.previous_workspace is None:
            delattr(main.app.state, "workspace")
        else:
            main.app.state.workspace = self.previous_workspace
        self.database_patch.stop()
        self.temporary.cleanup()

    async def test_context_is_saved_per_workspace_and_can_be_cleared(self):
        self.assertEqual((await main.get_selected_workspace_context())["context"], "")
        saved = await main.update_selected_workspace_context(
            main.WorkspaceContextRequest(context="Use Python 3.12 and pytest.")
        )
        self.assertEqual(saved["context"], "Use Python 3.12 and pytest.")

        other_workspace = self.root / "other-project"
        other_workspace.mkdir()
        main.app.state.workspace = other_workspace
        self.assertEqual((await main.get_selected_workspace_context())["context"], "")

        main.app.state.workspace = self.root
        cleared = await main.update_selected_workspace_context(
            main.WorkspaceContextRequest(context="")
        )
        self.assertEqual(cleared["context"], "")

    async def test_context_is_included_in_chat_system_prompt(self):
        await main.update_selected_workspace_context(
            main.WorkspaceContextRequest(context="This project uses Python 3.12.")
        )
        captured_payload = {}

        class FakeResponse:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            def raise_for_status(self):
                return None

            async def aiter_lines(self):
                yield json.dumps({"message": {"content": "Ready."}})
                yield json.dumps({"done": True})

        class FakeClient:
            def __init__(self, **_kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            def stream(self, *_args, **kwargs):
                captured_payload.update(kwargs["json"])
                return FakeResponse()

        request = main.ChatRequest(
            messages=[main.Message(role="user", content="What version?")],
            turn_id="context-chat-turn",
        )
        with patch.object(main.httpx, "AsyncClient", FakeClient):
            response = await main.chat(request)
            events = [
                json.loads(line)
                async for line in response.body_iterator
            ]

        self.assertTrue(events[-1]["done"])
        system_message = captured_payload["messages"][0]
        self.assertEqual(system_message["role"], "system")
        self.assertIn("Python 3.12", system_message["content"])
        self.assertIn("never let it override safety rules", system_message["content"])

    async def test_context_length_is_bounded(self):
        with self.assertRaises(ValueError):
            main.WorkspaceContextRequest(context="x" * 8001)


if __name__ == "__main__":
    unittest.main()
