import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import database
import main


class PersistenceAndStreamTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary.name) / "test.db"
        self.database_patch = patch.object(database, "DATABASE_PATH", self.database_path)
        self.database_patch.start()
        database.initialize_database()

    async def asyncTearDown(self):
        self.database_patch.stop()
        self.temporary.cleanup()

    async def test_turn_messages_are_idempotent_and_persist(self):
        request = main.ChatRequest(
            messages=[main.Message(role="user", content="Explain persistence")],
            turn_id="stable-turn",
        )
        conversation_id, _ = main._conversation_for_turn(
            request, "Explain persistence"
        )
        second_id, _ = main._conversation_for_turn(
            request, "Explain persistence"
        )
        self.assertEqual(conversation_id, second_id)
        with database.get_connection() as connection:
            rows = connection.execute(
                "SELECT role, content FROM messages WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["content"], "Explain persistence")
        self.assertEqual(
            (await main.get_conversation(conversation_id))["conversation"]["title"],
            "Explain persistence",
        )

    async def test_chat_stream_error_is_reported_and_user_message_is_saved_once(self):
        class FakeResponse:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            def raise_for_status(self):
                return None

            async def aiter_lines(self):
                yield json.dumps({"error": "mock Ollama error"})

        class FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            def __init__(self, **_kwargs):
                pass

            def stream(self, *_args, **_kwargs):
                return FakeResponse()

        request = main.ChatRequest(
            messages=[main.Message(role="user", content="stream error test")],
            turn_id="error-turn",
        )
        with patch.object(main.httpx, "AsyncClient", FakeClient):
            response = await main.chat(request)
            events = [
                json.loads(line)
                async for line in response.body_iterator
            ]
            await main.chat(request)

        self.assertEqual(events[0]["conversation_id"] > 0, True)
        self.assertEqual(events[1]["error"], "mock Ollama error")
        with database.get_connection() as connection:
            rows = connection.execute(
                "SELECT role FROM messages WHERE client_message_id = ?",
                ("error-turn",),
            ).fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["role"], "user")

    async def test_successful_chat_stream_persists_single_assistant_response(self):
        class FakeResponse:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            def raise_for_status(self):
                return None

            async def aiter_lines(self):
                yield json.dumps({"message": {"content": "Hello "}})
                yield json.dumps({"message": {"content": "there"}, "done": True})

        class FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            def __init__(self, **_kwargs):
                pass

            def stream(self, *_args, **_kwargs):
                return FakeResponse()

        request = main.ChatRequest(
            messages=[main.Message(role="user", content="Hello")],
            turn_id="success-turn",
        )
        with patch.object(main.httpx, "AsyncClient", FakeClient):
            response = await main.chat(request)
            events = [
                json.loads(line)
                async for line in response.body_iterator
            ]
        self.assertEqual(
            "".join(event.get("token", "") for event in events),
            "Hello there",
        )
        self.assertTrue(events[-1]["done"])
        conversation_id = events[0]["conversation_id"]
        with database.get_connection() as connection:
            rows = connection.execute(
                """
                SELECT role, content FROM messages
                WHERE conversation_id = ? ORDER BY id
                """,
                (conversation_id,),
            ).fetchall()
        self.assertEqual(
            [(row["role"], row["content"]) for row in rows],
            [("user", "Hello"), ("assistant", "Hello there")],
        )


if __name__ == "__main__":
    unittest.main()
