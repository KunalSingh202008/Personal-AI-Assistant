import asyncio
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from workspace_tools import (
    ARGUMENT_MODELS,
    ApprovalRequired,
    ToolValidationError,
    WorkspaceTools,
    _run_process,
    validate_tool_call,
)
from action_policy import classify_action
from local_server import _server_error


class WorkspaceToolTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.tools = WorkspaceTools(self.root)

    async def asyncTearDown(self):
        self.temporary.cleanup()

    def test_tool_schema_rejects_unknown_tools_and_arguments(self):
        with self.assertRaises(ToolValidationError):
            validate_tool_call("execute_shell", {"command": "whoami"})
        with self.assertRaises(ToolValidationError):
            validate_tool_call("read_file", {"path": "file.txt", "extra": True})

    def test_action_policy_covers_every_exposed_tool_and_blocks_unknown_actions(self):
        approval_required = {
            "write_file",
            "run_command",
            "git_commit",
            "start_local_server",
        }
        for name in ARGUMENT_MODELS:
            policy = classify_action(name)
            self.assertNotEqual(policy.risk, "RED", name)
            self.assertEqual(policy.requires_approval, name in approval_required)
        self.assertEqual(classify_action("execute_shell").risk, "RED")

    async def test_paths_are_confined_and_sensitive_files_are_blocked(self):
        (self.root / "safe.txt").write_text("safe", encoding="utf-8")
        (self.root / ".env").write_text("TOKEN=hidden", encoding="utf-8")
        (self.root / "private.sqlite3").write_bytes(b"database")
        with self.assertRaises(ToolValidationError):
            await self.tools.execute("read_file", {"path": "..\\outside.txt"})
        with self.assertRaises(ToolValidationError):
            await self.tools.execute("read_file", {"path": ".env"})
        with self.assertRaises(ToolValidationError):
            await self.tools.execute("read_file", {"path": "private.sqlite3"})
        self.assertEqual(
            await self.tools.execute("read_file", {"path": "safe.txt"}),
            "safe",
        )

    async def test_read_size_limit_and_secret_redaction(self):
        (self.root / "large.txt").write_bytes(b"x" * 1_000_001)
        (self.root / "settings.txt").write_text(
            "api_key=secret-value\npassword: my-password",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ToolValidationError, "1 MB"):
            await self.tools.execute("read_file", {"path": "large.txt"})
        value = await self.tools.execute("read_file", {"path": "settings.txt"})
        self.assertNotIn("secret-value", value)
        self.assertNotIn("my-password", value)
        self.assertIn("[REDACTED]", value)

    async def test_write_requires_approval_and_has_diff_before_writing(self):
        (self.root / "existing.txt").write_text("old\n", encoding="utf-8")
        with self.assertRaises(ApprovalRequired) as raised:
            await self.tools.execute(
                "write_file",
                {"path": "existing.txt", "content": "new\n"},
            )
        approval = raised.exception
        self.assertIn("-old", approval.diff)
        self.assertIn("+new", approval.diff)
        self.assertEqual((self.root / "existing.txt").read_text(encoding="utf-8"), "old\n")
        await self.tools.apply_write(
            approval.arguments["path"],
            approval.arguments["content"],
            approval.arguments["expected_sha256"],
        )
        self.assertEqual((self.root / "existing.txt").read_text(encoding="utf-8"), "new\n")

    async def test_write_refuses_to_overwrite_changes_since_approval(self):
        target = self.root / "existing.txt"
        target.write_text("before\n", encoding="utf-8")
        with self.assertRaises(ApprovalRequired) as raised:
            await self.tools.execute(
                "write_file",
                {"path": "existing.txt", "content": "approved edit\n"},
            )
        target.write_text("user change\n", encoding="utf-8")
        with self.assertRaisesRegex(ToolValidationError, "changed after approval"):
            await self.tools.apply_write(
                raised.exception.arguments["path"],
                raised.exception.arguments["content"],
                raised.exception.arguments["expected_sha256"],
            )
        self.assertEqual(target.read_text(encoding="utf-8"), "user change\n")

    async def test_unchanged_write_does_not_create_an_approval_request(self):
        (self.root / "unchanged.txt").write_text("same\n", encoding="utf-8")
        with self.assertRaisesRegex(ToolValidationError, "unchanged"):
            await self.tools.execute(
                "write_file",
                {"path": "unchanged.txt", "content": "same\n"},
            )

    async def test_generated_python_and_json_are_validated_before_approval(self):
        with self.assertRaisesRegex(
            ToolValidationError,
            r"syntax error at line 1, column \d+: unterminated f-string literal",
        ):
            await self.tools.execute(
                "write_file",
                {
                    "path": "app.py",
                    "content": 'message = f"broken\nstring"\n',
                },
            )
        with self.assertRaisesRegex(ToolValidationError, "Generated JSON is invalid"):
            await self.tools.execute(
                "write_file",
                {"path": "data.json", "content": '{"items": ]'},
            )
        self.assertFalse((self.root / "app.py").exists())
        self.assertFalse((self.root / "data.json").exists())

        with self.assertRaises(ApprovalRequired):
            await self.tools.execute(
                "write_file",
                {
                    "path": "app.py",
                    "content": 'message = f"valid"\n',
                },
            )

    async def test_commands_are_allowlisted_and_require_approval(self):
        with self.assertRaises(ApprovalRequired) as raised:
            await self.tools.execute("run_command", {"command": "npm run build"})
        self.assertEqual(raised.exception.arguments["command"], "npm run build")
        with self.assertRaises(ToolValidationError):
            await self.tools.execute("run_command", {"command": "whoami"})

    async def test_local_server_requires_approval_and_reports_only_confirmed_health(self):
        script = self.root / "app.py"
        script.write_text(
            """
import os
from http.server import BaseHTTPRequestHandler, HTTPServer

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")
        else:
            self.send_response(404)
            self.end_headers()

HTTPServer((os.environ["NEXUS_HOST"], int(os.environ["NEXUS_PORT"])), Handler).serve_forever()
""".strip(),
            encoding="utf-8",
        )
        with self.assertRaises(ApprovalRequired) as raised:
            await self.tools.execute(
                "start_local_server",
                {"script": "app.py", "health_path": "/health"},
            )
        self.assertEqual(raised.exception.policy.risk, "AMBER")
        source_hash = raised.exception.arguments["expected_sha256"]
        script.write_text(
            script.read_text(encoding="utf-8") + "\n# changed after request\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ToolValidationError, "changed after approval"):
            await self.tools.start_approved_local_server(
                "app.py",
                "/health",
                source_hash,
            )
        script.write_text(
            script.read_text(encoding="utf-8").replace(
                "\n# changed after request\n", ""
            ),
            encoding="utf-8",
        )

        from local_server import SERVERS, start_local_server, stop_local_server

        server_id, url = await start_local_server(
            self.root, "app.py", "/health"
        )
        try:
            self.assertTrue(url.startswith("http://127.0.0.1:"))
            self.assertIn(server_id, SERVERS)
            import httpx

            async with httpx.AsyncClient(trust_env=False) as client:
                response = await client.get(f"{url}/health")
            self.assertEqual(response.status_code, 200)
        finally:
            await stop_local_server(server_id)
        self.assertNotIn(server_id, SERVERS)

    async def test_process_timeout_and_output_limit(self):
        with patch("workspace_tools.MAX_COMMAND_SECONDS", 0.05):
            with self.assertRaisesRegex(ToolValidationError, "timeout"):
                await _run_process(
                    [sys.executable, "-c", "import time; time.sleep(2)"],
                    self.root,
                )

        _, output = await _run_process(
            [sys.executable, "-c", "print('x' * 30000)"],
            self.root,
        )
        self.assertLessEqual(len(output), 12_100)
        self.assertIn("Output limit reached", output)

    async def test_unconfigured_web_search_is_explicit(self):
        result = await self.tools.execute("web_search", {"query": "Nexus AI"})
        self.assertIn("not configured", result)

    def test_server_health_error_distinguishes_running_from_exited_process(self):
        class FakeProcess:
            def __init__(self, returncode):
                self.returncode = returncode

            def poll(self):
                return self.returncode

        running = _server_error(bytearray(), FakeProcess(None))
        exited = _server_error(bytearray(), FakeProcess(1))

        self.assertIn("remained running", running)
        self.assertIn("did not return HTTP 200", running)
        self.assertIn("exited with code 1", exited)


if __name__ == "__main__":
    unittest.main()
