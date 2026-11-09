import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import agent
import database
import main


class AgentLoopTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.database_patch = patch.object(
            database, "DATABASE_PATH", self.root / "test.db"
        )
        self.database_patch.start()
        database.initialize_database()
        main.APPROVALS.clear()
        with database.get_connection() as connection:
            self.conversation_id = connection.execute(
                "INSERT INTO conversations (title) VALUES (?)",
                ("Agent integration",),
            ).lastrowid

        (self.root / "sample.txt").write_text("before\n", encoding="utf-8")
        (self.root / "package.json").write_text(
            json.dumps({
                "name": "agent-test",
                "version": "1.0.0",
                "scripts": {
                    "test": "node -e \"console.log('tests passed')\"",
                },
            }),
            encoding="utf-8",
        )

    async def asyncTearDown(self):
        main.APPROVALS.clear()
        self.database_patch.stop()
        self.temporary.cleanup()

    def test_goal_requires_implementation_classification(self):
        self.assertFalse(agent._goal_requires_implementation("inspect the files"))
        self.assertFalse(agent._goal_requires_implementation("list files"))
        self.assertFalse(agent._goal_requires_implementation("summarize README"))
        self.assertFalse(agent._goal_requires_implementation("explain this code"))
        self.assertFalse(agent._goal_requires_implementation("read the docs"))

        self.assertTrue(agent._goal_requires_implementation("create a file"))
        self.assertTrue(agent._goal_requires_implementation("fix this bug"))
        self.assertTrue(agent._goal_requires_implementation("implement this feature"))
        self.assertTrue(
            agent._goal_requires_implementation("Inspect this and update it if needed")
        )
        self.assertTrue(
            agent._goal_requires_implementation("inspect the files and update the bug if needed")
        )

    def test_requested_verification_command_is_preserved(self):
        goal = "Run python -m unittest nexus_smoke_test -v"
        messages = [{"role": "user", "content": "Please run python -m unittest nexus_smoke_test -v"}]
        self.assertEqual(
            agent._requested_verification_command(goal, messages),
            "python -m unittest nexus_smoke_test -v",
        )
        self.assertEqual(
            agent._normalize_run_command_arguments(
                goal,
                messages,
                {"command": "python -m unittest app"},
            )["command"],
            "python -m unittest nexus_smoke_test -v",
        )

    def test_message_content_rejects_empty_or_whitespace_only_values(self):
        with self.assertRaisesRegex(ValueError, "empty or whitespace"):
            main.Message.model_validate({"role": "user", "content": ""})
        with self.assertRaisesRegex(ValueError, "empty or whitespace"):
            main.Message.model_validate({"role": "assistant", "content": "   "})
        self.assertEqual(
            main.Message.model_validate({"role": "user", "content": " explain "}).content,
            " explain ",
        )

    async def test_reads_proposes_approved_edit_and_approved_test_command(self):
        task_id = "verified-agent-turn"
        database.create_agent_task(
            task_id,
            self.conversation_id,
            "Change sample and test",
            str(self.root),
        )
        actions = [
            {"type": "plan", "steps": ["Read the sample", "Edit and test it"]},
            {"type": "tool_call", "tool": "read_file", "arguments": {"path": "sample.txt"}},
            {
                "type": "tool_call",
                "tool": "write_file",
                "arguments": {"path": "sample.txt", "content": "after\n"},
            },
            {
                "type": "tool_call",
                "tool": "run_command",
                "arguments": {"command": "npm test"},
            },
            {"type": "final", "content": "The edit and test completed."},
        ]
        model_inputs = []

        class FakeResponse:
            def __init__(self, action):
                self.action = action

            def raise_for_status(self):
                return None

            def json(self):
                return {"message": {"content": json.dumps(self.action)}}

        class FakeClient:
            def __init__(self, **_kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            async def post(self, *_args, **_kwargs):
                model_inputs.append(_kwargs["json"]["messages"])
                return FakeResponse(actions.pop(0))

        outcomes = []

        def register(approval_id, details):
            return main._register_approval(approval_id, details)

        def authorize(*args):
            return main._authorize_approval(*args)

        def complete(approval_id, outcome):
            outcomes.append(outcome)
            main._complete_approval(approval_id, outcome)

        def record_activity(*event):
            database.record_agent_activity(*event)

        events = []
        with patch.object(agent.httpx, "AsyncClient", FakeClient):
            stream = agent.agent_stream(
                root=self.root,
                conversation_id=self.conversation_id,
                messages=[{"role": "user", "content": "Change sample and test"}],
                turn_id="agent-turn",
                register_approval=register,
                clear_approval=main._clear_approval,
                authorize_approval=authorize,
                complete_approval=complete,
                record_activity=record_activity,
                task_id=task_id,
                project_context="This project uses pytest.",
            )
            async for line in stream:
                event = json.loads(line)
                events.append(event)
                if event["type"] == "approval_required":
                    await main.decide_agent_approval(
                        event["approval_id"],
                        main.ApprovalRequest(
                            approved=True,
                            action_digest=event["action_digest"],
                        ),
                    )

        self.assertEqual(
            (self.root / "sample.txt").read_text(encoding="utf-8"),
            "after\n",
        )
        self.assertEqual(
            [event["action"] for event in events if event["type"] == "approval_required"],
            ["write_file", "run_command"],
        )
        self.assertTrue(
            any(
                event["type"] == "tool_result"
                and "before" in event.get("output", "")
                for event in events
            )
        )
        self.assertTrue(
            any(
                event["type"] == "tool_result"
                and "tests passed" in event.get("output", "")
                for event in events
            )
        )
        self.assertEqual(events[-1]["type"], "done")
        task = database.get_agent_task(task_id)
        self.assertEqual(task["state"], "completed")
        self.assertEqual(task["verification_status"], "verified")
        self.assertEqual(task["changed_files"], ["sample.txt"])
        self.assertEqual(task["tool_results"][-1]["tool"], "run_command")
        self.assertEqual(outcomes, ["executed", "executed"])
        audit_events = database.list_agent_activity()
        self.assertIn("completed", [item["event"] for item in audit_events])
        self.assertIn("approval_requested", [item["event"] for item in audit_events])
        with database.get_connection() as connection:
            saved = connection.execute(
                "SELECT content FROM messages WHERE client_message_id = ?",
                ("agent-turn:assistant",),
            ).fetchone()
        self.assertEqual(saved["content"], "The edit and test completed.")
        self.assertIn("This project uses pytest.", model_inputs[0][0]["content"])

    async def test_cancelled_approval_clears_pending_request_without_writing(self):
        action = {
            "type": "tool_call",
            "tool": "write_file",
            "arguments": {"path": "sample.txt", "content": "after\n"},
        }

        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {"message": {"content": json.dumps(action)}}

        class FakeClient:
            def __init__(self, **_kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            async def post(self, *_args, **_kwargs):
                return FakeResponse()

        with patch.object(agent.httpx, "AsyncClient", FakeClient):
            stream = agent.agent_stream(
                root=self.root,
                conversation_id=self.conversation_id,
                messages=[{"role": "user", "content": "Edit sample"}],
                turn_id="cancelled-approval",
                register_approval=main._register_approval,
                clear_approval=main._clear_approval,
                authorize_approval=main._authorize_approval,
                complete_approval=lambda *_args: None,
                record_activity=database.record_agent_activity,
            )
            while True:
                event = json.loads(await anext(stream))
                if event["type"] == "approval_required":
                    break
            await stream.aclose()

        self.assertNotIn(event["approval_id"], main.APPROVALS)
        self.assertEqual((self.root / "sample.txt").read_text(encoding="utf-8"), "before\n")
        self.assertIn(
            "cancelled",
            [entry["event"] for entry in database.list_agent_activity()],
        )

    def test_parser_normalizes_json_and_native_tool_call_shapes(self):
        self.assertEqual(
            agent._parse_model_action(
                json.dumps({
                    "name": "read_file",
                    "arguments": {"path": "sample.txt"},
                })
            ),
            {
                "type": "tool_call",
                "tool": "read_file",
                "arguments": {"path": "sample.txt"},
            },
        )
        self.assertEqual(
            agent._parse_model_action(
                "",
                [{
                    "function": {
                        "name": "read_file",
                        "arguments": "{\"path\":\"sample.txt\"}",
                    },
                }],
            )["arguments"],
            {"path": "sample.txt"},
        )
        with self.assertRaisesRegex(ValueError, "exactly one"):
            agent._parse_model_action(
                "",
                [
                    {"function": {"name": "read_file", "arguments": {}}},
                    {"function": {"name": "git_status", "arguments": {}}},
                ],
            )
        with self.assertRaisesRegex(ValueError, "valid JSON"):
            agent._parse_model_action(
                "",
                [{"function": {"name": "read_file", "arguments": "{"}}],
            )

    async def test_unsupported_tool_is_rejected_with_bounded_recovery(self):
        actions = [
            {
                "type": "tool_call",
                "tool": "execute_shell",
                "arguments": {"command": "whoami"},
            },
            {"type": "final", "content": "I stopped without running an unsupported tool."},
        ]
        model_inputs = []

        class FakeResponse:
            def __init__(self, action):
                self.action = action

            def raise_for_status(self):
                return None

            def json(self):
                return {"message": {"content": json.dumps(self.action)}}

        class FakeClient:
            def __init__(self, **_kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            async def post(self, *_args, **kwargs):
                model_inputs.append(kwargs["json"])
                return FakeResponse(actions.pop(0))

        with patch.object(agent.httpx, "AsyncClient", FakeClient):
            events = [
                json.loads(line)
                async for line in agent.agent_stream(
                    root=self.root,
                    conversation_id=self.conversation_id,
                    messages=[{"role": "user", "content": "Run whoami"}],
                    turn_id="unsupported-tool",
                    register_approval=main._register_approval,
                    clear_approval=main._clear_approval,
                    authorize_approval=main._authorize_approval,
                    complete_approval=main._complete_approval,
                    record_activity=database.record_agent_activity,
                )
            ]

        self.assertEqual(events[-1]["type"], "done")
        self.assertFalse(any(event["type"] == "tool_start" for event in events))
        self.assertTrue(any(event["type"] == "status" for event in events))
        self.assertIn("unsupported", model_inputs[1]["messages"][-1]["content"])
        self.assertTrue(model_inputs[0]["tools"])
        tool_variants = [
            variant
            for variant in model_inputs[0]["format"]["oneOf"]
            if variant["properties"]["type"].get("const") == "tool_call"
        ]
        self.assertEqual(
            {variant["properties"]["tool"]["const"] for variant in tool_variants},
            {schema["name"] for schema in agent.TOOL_SCHEMAS},
        )
        self.assertTrue(
            all(
                variant["additionalProperties"] is False
                for variant in model_inputs[0]["format"]["oneOf"]
            )
        )

    async def test_malformed_tool_arguments_are_corrected_before_execution(self):
        actions = [
            {
                "type": "tool_call",
                "tool": "read_file",
                "arguments": {"path": "sample.txt", "unexpected": True},
            },
            {
                "type": "tool_call",
                "tool": "read_file",
                "arguments": {"path": "sample.txt"},
            },
            {"type": "final", "content": "The file was read."},
        ]
        model_inputs = []

        class FakeResponse:
            def __init__(self, action):
                self.action = action

            def raise_for_status(self):
                return None

            def json(self):
                return {"message": {"content": json.dumps(self.action)}}

        class FakeClient:
            def __init__(self, **_kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            async def post(self, *_args, **kwargs):
                model_inputs.append(kwargs["json"]["messages"])
                return FakeResponse(actions.pop(0))

        with patch.object(agent.httpx, "AsyncClient", FakeClient):
            events = [
                json.loads(line)
                async for line in agent.agent_stream(
                    root=self.root,
                    conversation_id=self.conversation_id,
                    messages=[{"role": "user", "content": "Read the sample"}],
                    turn_id="malformed-tool",
                    register_approval=main._register_approval,
                    clear_approval=main._clear_approval,
                    authorize_approval=main._authorize_approval,
                    complete_approval=main._complete_approval,
                    record_activity=database.record_agent_activity,
                )
            ]

        self.assertEqual(events[-1]["type"], "done")
        self.assertEqual(
            [event["tool"] for event in events if event["type"] == "tool_start"],
            ["read_file"],
        )
        self.assertTrue(
            any(
                "argument fields" in message["content"]
                for message in model_inputs[1]
                if message["role"] == "user"
            )
        )
        self.assertEqual(
            sum(event["type"] == "tool_start" for event in events),
            1,
        )

    async def test_repeated_plan_is_rejected_and_agent_continues_existing_plan(self):
        actions = [
            {"type": "plan", "steps": ["Inspect the sample", "Report the result"]},
            *[
                {"type": "plan", "steps": ["Inspect the sample", "Report the result"]}
                for _ in range(agent.MAX_PLAN_RECOVERY_ATTEMPTS)
            ],
            {
                "type": "tool_call",
                "tool": "read_file",
                "arguments": {"path": "sample.txt"},
            },
            {"type": "final", "content": "The sample was inspected."},
        ]
        model_inputs = []

        class FakeResponse:
            def __init__(self, action):
                self.action = action

            def raise_for_status(self):
                return None

            def json(self):
                return {"message": {"content": json.dumps(self.action)}}

        class FakeClient:
            def __init__(self, **_kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            async def post(self, *_args, **kwargs):
                payload = dict(kwargs["json"])
                payload["messages"] = [
                    dict(message) for message in kwargs["json"]["messages"]
                ]
                model_inputs.append(payload)
                return FakeResponse(actions.pop(0))

        with patch.object(agent.httpx, "AsyncClient", FakeClient):
            events = [
                json.loads(line)
                async for line in agent.agent_stream(
                    root=self.root,
                    conversation_id=self.conversation_id,
                    messages=[{"role": "user", "content": "Inspect the sample"}],
                    turn_id="repeated-plan",
                    register_approval=main._register_approval,
                    clear_approval=main._clear_approval,
                    authorize_approval=main._authorize_approval,
                    complete_approval=main._complete_approval,
                    record_activity=database.record_agent_activity,
                )
            ]

        self.assertEqual(events[-1]["type"], "done")
        self.assertEqual(sum(event["type"] == "plan" for event in events), 1)
        self.assertEqual(
            [event["tool"] for event in events if event["type"] == "tool_start"],
            ["read_file"],
        )
        self.assertTrue(
            any(
                event["type"] == "status"
                and "plan was already recorded" in event["message"]
                for event in events
            )
        )
        self.assertIn(
            "Do not return or revise a plan",
            model_inputs[2]["messages"][-1]["content"],
        )
        self.assertNotIn(
            "plan",
            {
                schema["properties"].get("type", {}).get("const")
                for schema in model_inputs[1]["format"]["oneOf"]
            },
        )

    async def test_unavailable_approved_command_is_reported_for_safe_recovery(self):
        actions = [
            {
                "type": "tool_call",
                "tool": "run_command",
                "arguments": {"command": "pytest"},
            },
            {
                "type": "tool_call",
                "tool": "run_command",
                "arguments": {"command": "python -m unittest app"},
            },
            {"type": "final", "content": "The installed test command passed."},
        ]

        class FakeResponse:
            def __init__(self, action):
                self.action = action

            def raise_for_status(self):
                return None

            def json(self):
                return {"message": {"content": json.dumps(self.action)}}

        class FakeClient:
            def __init__(self, **_kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            async def post(self, *_args, **_kwargs):
                return FakeResponse(actions.pop(0))

        async def run_command(command):
            if command == "pytest":
                raise agent.ToolValidationError(
                    "Required command is unavailable: pytest"
                )
            return "Exit code: 0\nRan 2 tests."

        events = []
        with (
            patch.object(agent.httpx, "AsyncClient", FakeClient),
            patch.object(
                agent.WorkspaceTools,
                "run_approved_command",
                side_effect=run_command,
            ),
        ):
            stream = agent.agent_stream(
                root=self.root,
                conversation_id=self.conversation_id,
                messages=[{"role": "user", "content": "Verify the app"}],
                turn_id="unavailable-approved-command",
                register_approval=main._register_approval,
                clear_approval=main._clear_approval,
                authorize_approval=main._authorize_approval,
                complete_approval=main._complete_approval,
                record_activity=database.record_agent_activity,
            )
            async for line in stream:
                event = json.loads(line)
                events.append(event)
                if event["type"] == "approval_required":
                    await main.decide_agent_approval(
                        event["approval_id"],
                        main.ApprovalRequest(
                            approved=True,
                            action_digest=event["action_digest"],
                        ),
                    )

        results = [
            event["output"]
            for event in events
            if event["type"] == "tool_result"
        ]
        self.assertEqual(events[-1]["type"], "done")
        self.assertEqual(len(results), 2)
        self.assertIn("Required command is unavailable: pytest", results[0])
        self.assertIn("Exit code: 0", results[1])
        self.assertEqual(
            [event["action"] for event in events if event["type"] == "approval_required"],
            ["run_command", "run_command"],
        )
        audit_events = database.list_agent_activity()
        self.assertIn("failed", [item["event"] for item in audit_events])
        self.assertIn("completed", [item["event"] for item in audit_events])

    async def test_empty_model_timeout_is_reported_with_actionable_error(self):
        task_id = "empty-model-timeout"
        database.create_agent_task(
            task_id,
            self.conversation_id,
            "Create and verify a module",
            str(self.root),
        )

        class FakeClient:
            def __init__(self, **_kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            async def post(self, *_args, **_kwargs):
                raise TimeoutError()

        with patch.object(agent.httpx, "AsyncClient", FakeClient):
            events = [
                json.loads(line)
                async for line in agent.agent_stream(
                    root=self.root,
                    conversation_id=self.conversation_id,
                    messages=[{
                        "role": "user",
                        "content": "Create and verify a module",
                    }],
                    turn_id="empty-model-timeout",
                    register_approval=main._register_approval,
                    clear_approval=main._clear_approval,
                    authorize_approval=main._authorize_approval,
                    complete_approval=main._complete_approval,
                    record_activity=database.record_agent_activity,
                    task_id=task_id,
                )
            ]

        self.assertEqual(events[-1]["type"], "error")
        self.assertIn("did not respond before", events[-1]["error"])
        self.assertEqual(database.get_agent_task(task_id)["state"], "blocked")

    async def test_python_syntax_error_is_reported_before_write_approval(self):
        task_id = "generated-python-syntax-verified"
        database.create_agent_task(
            task_id,
            self.conversation_id,
            "Create and verify a Python module",
            str(self.root),
        )
        valid_source = (
            "import unittest\n"
            "class GeneratedTests(unittest.TestCase):\n"
            "    def test_sanity(self):\n"
            "        self.assertEqual(2 + 2, 4)\n"
        )
        actions = [
            {
                "native_tool_call": {
                    "name": "write_file",
                    "arguments": {
                        "path": "app.py",
                        "content": 'message = f"broken\nstring"\n',
                    },
                },
            },
            {
                "type": "tool_call",
                "tool": "write_file",
                "arguments": {
                    "path": "app.py",
                    "content": valid_source,
                },
            },
            {
                "type": "tool_call",
                "tool": "run_command",
                "arguments": {"command": "python -m unittest app"},
            },
            {"type": "final", "content": "The corrected module passed verification."},
        ]
        model_inputs = []

        class FakeResponse:
            def __init__(self, action):
                self.action = action

            def raise_for_status(self):
                return None

            def json(self):
                if "native_tool_call" in self.action:
                    return {
                        "message": {
                            "content": "",
                            "tool_calls": [{
                                "function": self.action["native_tool_call"],
                            }],
                        },
                    }
                return {"message": {"content": json.dumps(self.action)}}

        class FakeClient:
            def __init__(self, **_kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            async def post(self, *_args, **kwargs):
                model_inputs.append(kwargs["json"]["messages"])
                return FakeResponse(actions.pop(0))

        events = []
        with patch.object(agent.httpx, "AsyncClient", FakeClient):
            stream = agent.agent_stream(
                root=self.root,
                conversation_id=self.conversation_id,
                messages=[{
                    "role": "user",
                    "content": "Create and verify a Python module",
                }],
                turn_id="generated-python-syntax",
                register_approval=main._register_approval,
                clear_approval=main._clear_approval,
                authorize_approval=main._authorize_approval,
                complete_approval=main._complete_approval,
                record_activity=database.record_agent_activity,
                task_id=task_id,
            )
            async for line in stream:
                event = json.loads(line)
                events.append(event)
                if event["type"] == "approval_required":
                    await main.decide_agent_approval(
                        event["approval_id"],
                        main.ApprovalRequest(
                            approved=True,
                            action_digest=event["action_digest"],
                        ),
                    )

        self.assertEqual(events[-1]["type"], "done")
        approvals = [
            event for event in events if event["type"] == "approval_required"
        ]
        self.assertEqual(
            [event["action"] for event in approvals],
            ["write_file", "run_command"],
        )
        self.assertEqual(
            (self.root / "app.py").read_text(encoding="utf-8"),
            valid_source,
        )
        self.assertIn(
            "syntax error at line 1",
            next(
                message["content"]
                for message in model_inputs[1]
                if message["role"] == "user"
                and "Generated Python" in message["content"]
            ),
        )
        native_action_history = next(
            message["content"]
            for message in model_inputs[1]
            if message["role"] == "assistant"
            and '"tool": "write_file"' in message["content"]
        )
        self.assertEqual(
            json.loads(native_action_history)["arguments"]["content"],
            'message = f"broken\nstring"\n',
        )
        self.assertTrue(any(
            event["type"] == "tool_result"
            and event.get("tool") == "run_command"
            and event.get("output", "").startswith("Exit code: 0")
            for event in events
        ))
        task = database.get_agent_task(task_id)
        self.assertEqual(task["state"], "completed")
        self.assertEqual(task["verification_status"], "verified")

    async def test_repeated_failed_action_blocks_without_retrying_operation(self):
        task_id = "repeated-invalid-python"
        database.create_agent_task(
            task_id,
            self.conversation_id,
            "Create valid Python",
            str(self.root),
        )
        invalid_action = {
            "type": "tool_call",
            "tool": "write_file",
            "arguments": {
                "path": "generated.py",
                "content": 'message = f"broken\nstring"\n',
            },
        }
        actions = [invalid_action, invalid_action, invalid_action]

        class FakeResponse:
            def __init__(self, action):
                self.action = action

            def raise_for_status(self):
                return None

            def json(self):
                return {"message": {"content": json.dumps(self.action)}}

        class FakeClient:
            def __init__(self, **_kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            async def post(self, *_args, **_kwargs):
                return FakeResponse(actions.pop(0))

        events = []
        with patch.object(agent.httpx, "AsyncClient", FakeClient):
            events = [
                json.loads(line)
                async for line in agent.agent_stream(
                    root=self.root,
                    conversation_id=self.conversation_id,
                    messages=[{
                        "role": "user",
                        "content": "Create valid Python",
                    }],
                    turn_id="repeated-invalid-python",
                    register_approval=main._register_approval,
                    clear_approval=main._clear_approval,
                    authorize_approval=main._authorize_approval,
                    complete_approval=main._complete_approval,
                    record_activity=database.record_agent_activity,
                    task_id=task_id,
                )
            ]

        self.assertEqual(events[-1]["type"], "done")
        self.assertEqual(
            sum(event["type"] == "tool_start" for event in events),
            1,
        )
        self.assertEqual(
            sum(event["type"] == "task_progress" and event.get("status") == "repairing"
                for event in events),
            1,
        )
        self.assertEqual(
            database.get_agent_task(task_id)["state"],
            "blocked",
        )
        self.assertFalse((self.root / "generated.py").exists())
        self.assertTrue(
            any(event["type"] == "task_progress" and event.get("error") for event in events)
        )

    async def test_read_only_task_allows_final_response_without_file_changes(self):
        task_id = "read-only-task"
        database.create_agent_task(
            task_id,
            self.conversation_id,
            "Inspect the sample file and summarize it",
            str(self.root),
        )
        actions = [
            {"type": "plan", "steps": ["Read the sample file", "Summarize it"]},
            {"type": "tool_call", "tool": "read_file", "arguments": {"path": "sample.txt"}},
            {"type": "final", "content": "The sample file says: before."},
        ]

        class FakeResponse:
            def __init__(self, action):
                self.action = action

            def raise_for_status(self):
                return None

            def json(self):
                return {"message": {"content": json.dumps(self.action)}}

        class FakeClient:
            def __init__(self, **_kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            async def post(self, *_args, **_kwargs):
                return FakeResponse(actions.pop(0))

        with patch.object(agent.httpx, "AsyncClient", FakeClient):
            events = [
                json.loads(line)
                async for line in agent.agent_stream(
                    root=self.root,
                    conversation_id=self.conversation_id,
                    messages=[{"role": "user", "content": "Inspect the sample file and summarize it"}],
                    turn_id="read-only-task",
                    register_approval=main._register_approval,
                    clear_approval=main._clear_approval,
                    authorize_approval=main._authorize_approval,
                    complete_approval=main._complete_approval,
                    record_activity=database.record_agent_activity,
                    task_id=task_id,
                )
            ]

        self.assertEqual(events[-1]["type"], "done")
        self.assertEqual(database.get_agent_task(task_id)["state"], "completed")
        self.assertEqual(database.get_agent_task(task_id)["changed_files"], [])
        self.assertTrue(any(event["type"] == "final" and event["content"].startswith("The sample file") for event in events))

    async def test_task_cannot_start_server_before_verified_file_changes(self):
        task_id = "server-requires-verification"
        database.create_agent_task(
            task_id,
            self.conversation_id,
            "Build and run the requested app",
            str(self.root),
        )
        actions = [
            {
                "type": "tool_call",
                "tool": "start_local_server",
                "arguments": {"script": "app.py", "health_path": "/health"},
            },
            {"type": "final", "content": "The app is running."},
            {"type": "final", "content": "The app is running."},
            {"type": "final", "content": "The app is running."},
        ]
        model_inputs = []

        class FakeResponse:
            def __init__(self, action):
                self.action = action

            def raise_for_status(self):
                return None

            def json(self):
                return {"message": {"content": json.dumps(self.action)}}

        class FakeClient:
            def __init__(self, **_kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            async def post(self, *_args, **kwargs):
                model_inputs.append(kwargs["json"]["messages"])
                return FakeResponse(actions.pop(0))

        with patch.object(agent.httpx, "AsyncClient", FakeClient):
            events = [
                json.loads(line)
                async for line in agent.agent_stream(
                    root=self.root,
                    conversation_id=self.conversation_id,
                    messages=[{
                        "role": "user",
                        "content": "Build and run the requested app",
                    }],
                    turn_id="server-before-verification",
                    register_approval=main._register_approval,
                    clear_approval=main._clear_approval,
                    authorize_approval=main._authorize_approval,
                    complete_approval=main._complete_approval,
                    record_activity=database.record_agent_activity,
                    task_id=task_id,
                )
            ]

        self.assertFalse(any(
            event["type"] == "approval_required"
            and event.get("action") == "start_local_server"
            for event in events
        ))
        self.assertFalse(any(
            event["type"] == "tool_start"
            and event.get("tool") == "start_local_server"
            for event in events
        ))
        self.assertTrue(any(
            "cannot start before" in message["content"]
            for message in model_inputs[1]
            if message["role"] == "user"
        ))
        self.assertEqual(
            database.get_agent_task(task_id)["state"],
            "blocked",
        )

    async def test_failed_server_health_check_guides_environment_binding_repair(self):
        task_id = "server-health-repair"
        database.create_agent_task(
            task_id,
            self.conversation_id,
            "Create and start a verified local app",
            str(self.root),
        )
        initial_source = (
            "import os\n"
            "import unittest\n"
            "HOST = '127.0.0.1'\n"
            "PORT = 8000\n"
            "class AppTests(unittest.TestCase):\n"
            "    def test_sanity(self):\n"
            "        self.assertTrue(True)\n"
        )
        corrected_source = (
            "import os\n"
            "import unittest\n"
            "HOST = os.environ.get('NEXUS_HOST', '127.0.0.1')\n"
            "PORT = int(os.environ.get('NEXUS_PORT', '8000'))\n"
            "class AppTests(unittest.TestCase):\n"
            "    def test_sanity(self):\n"
            "        self.assertTrue(True)\n"
        )
        actions = [
            {
                "type": "tool_call",
                "tool": "write_file",
                "arguments": {"path": "app.py", "content": initial_source},
            },
            {
                "type": "tool_call",
                "tool": "run_command",
                "arguments": {"command": "python -m unittest app"},
            },
            {
                "type": "tool_call",
                "tool": "start_local_server",
                "arguments": {"script": "app.py", "health_path": "/health"},
            },
            {
                "type": "tool_call",
                "tool": "read_file",
                "arguments": {"path": "app.py"},
            },
            {
                "type": "tool_call",
                "tool": "write_file",
                "arguments": {"path": "app.py", "content": corrected_source},
            },
            {
                "type": "tool_call",
                "tool": "run_command",
                "arguments": {"command": "python -m unittest app"},
            },
            {"type": "final", "content": "The repaired app passed verification."},
        ]
        model_inputs = []

        class FakeResponse:
            def __init__(self, action):
                self.action = action

            def raise_for_status(self):
                return None

            def json(self):
                return {"message": {"content": json.dumps(self.action)}}

        class FakeClient:
            def __init__(self, **_kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            async def post(self, *_args, **kwargs):
                model_inputs.append([
                    dict(message) for message in kwargs["json"]["messages"]
                ])
                return FakeResponse(actions.pop(0))

        async def successful_check(_command):
            return "Exit code: 0\nRan 1 test."

        events = []
        with (
            patch.object(agent.httpx, "AsyncClient", FakeClient),
            patch.object(
                agent.WorkspaceTools,
                "run_approved_command",
                side_effect=successful_check,
            ),
            patch.object(
                agent.WorkspaceTools,
                "start_approved_local_server",
                side_effect=RuntimeError(
                    "Local health check failed for http://127.0.0.1:64656/health "
                    "within 15 seconds. Server process exited with code None "
                    "before health verification."
                ),
            ),
        ):
            async for line in agent.agent_stream(
                root=self.root,
                conversation_id=self.conversation_id,
                messages=[{
                    "role": "user",
                    "content": "Create and start a verified local app",
                }],
                turn_id="server-health-repair",
                register_approval=main._register_approval,
                clear_approval=main._clear_approval,
                authorize_approval=main._authorize_approval,
                complete_approval=main._complete_approval,
                record_activity=database.record_agent_activity,
                task_id=task_id,
            ):
                event = json.loads(line)
                events.append(event)
                if event["type"] == "approval_required":
                    await main.decide_agent_approval(
                        event["approval_id"],
                        main.ApprovalRequest(
                            approved=True,
                            action_digest=event["action_digest"],
                        ),
                    )

        recovery_prompt = model_inputs[3][-1]["content"]
        self.assertIn("Local health check failed", recovery_prompt)
        self.assertIn("NEXUS_HOST", recovery_prompt)
        self.assertIn("NEXUS_PORT", recovery_prompt)
        self.assertEqual(
            [event["action"] for event in events if event["type"] == "approval_required"],
            ["write_file", "run_command", "start_local_server", "write_file", "run_command"],
        )
        self.assertEqual(
            (self.root / "app.py").read_text(encoding="utf-8"),
            corrected_source,
        )
        task = database.get_agent_task(task_id)
        self.assertEqual(task["state"], "completed")
        self.assertEqual(task["verification_status"], "verified")

    async def test_failed_verification_guides_repair_before_retry(self):
        task_id = "verification-repair"
        database.create_agent_task(
            task_id,
            self.conversation_id,
            "Create an app module with discoverable tests and pass verification",
            str(self.root),
        )
        initial_source = "VALUE = 1\n"
        repaired_source = (
            "import unittest\n"
            "class GeneratedTests(unittest.TestCase):\n"
            "    def test_sanity(self):\n"
            "        self.assertEqual(2 + 2, 4)\n"
        )
        actions = [
            {
                "type": "tool_call",
                "tool": "write_file",
                "arguments": {"path": "app.py", "content": initial_source},
            },
            {
                "type": "tool_call",
                "tool": "run_command",
                "arguments": {"command": "python -m unittest app"},
            },
            {
                "type": "tool_call",
                "tool": "read_file",
                "arguments": {"path": "app.py"},
            },
            {
                "type": "tool_call",
                "tool": "write_file",
                "arguments": {"path": "app.py", "content": initial_source},
            },
            {
                "type": "tool_call",
                "tool": "write_file",
                "arguments": {"path": "app.py", "content": repaired_source},
            },
            {
                "type": "tool_call",
                "tool": "run_command",
                "arguments": {"command": "python -m unittest app"},
            },
            {"type": "final", "content": "The repaired change passed verification."},
        ]
        model_inputs = []
        command_results = iter([
            "Exit code: 5\nRan 0 tests in 0.000s\nNO TESTS RAN",
            "Exit code: 0\nRan 2 tests.",
        ])

        class FakeResponse:
            def __init__(self, action):
                self.action = action

            def raise_for_status(self):
                return None

            def json(self):
                return {"message": {"content": json.dumps(self.action)}}

        class FakeClient:
            def __init__(self, **_kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            async def post(self, *_args, **kwargs):
                model_inputs.append([
                    dict(message) for message in kwargs["json"]["messages"]
                ])
                return FakeResponse(actions.pop(0))

        async def run_command(_command):
            return next(command_results)

        events = []
        with (
            patch.object(agent.httpx, "AsyncClient", FakeClient),
            patch.object(
                agent.WorkspaceTools,
                "run_approved_command",
                side_effect=run_command,
            ),
        ):
            stream = agent.agent_stream(
                root=self.root,
                conversation_id=self.conversation_id,
                messages=[{
                    "role": "user",
                    "content": (
                        "Create an app module with discoverable tests and pass verification"
                    ),
                }],
                turn_id="verification-repair",
                register_approval=main._register_approval,
                clear_approval=main._clear_approval,
                authorize_approval=main._authorize_approval,
                complete_approval=main._complete_approval,
                record_activity=database.record_agent_activity,
                task_id=task_id,
            )
            async for line in stream:
                event = json.loads(line)
                events.append(event)
                if event["type"] == "approval_required":
                    await main.decide_agent_approval(
                        event["approval_id"],
                        main.ApprovalRequest(
                            approved=True,
                            action_digest=event["action_digest"],
                        ),
                    )

        self.assertEqual(events[-1]["type"], "done")
        self.assertEqual(
            [event["action"] for event in events if event["type"] == "approval_required"],
            ["write_file", "run_command", "write_file", "run_command"],
        )
        self.assertIn(
            "Ran 0 tests in 0.000s",
            model_inputs[4][-1]["content"],
        )
        self.assertIn(
            "unittest.TestCase",
            model_inputs[4][-1]["content"],
        )
        self.assertEqual(
            (self.root / "app.py").read_text(encoding="utf-8"),
            repaired_source,
        )
        task = database.get_agent_task(task_id)
        self.assertEqual(task["state"], "completed")
        self.assertEqual(task["verification_status"], "verified")

    async def test_task_cannot_complete_after_file_change_without_verification(self):
        task_id = "unverified-agent-task"
        database.create_agent_task(
            task_id,
            self.conversation_id,
            "Create an unverified file",
            str(self.root),
        )
        actions = [
            {
                "type": "tool_call",
                "tool": "write_file",
                "arguments": {"path": "new.txt", "content": "new\n"},
            },
            {"type": "final", "content": "Everything is done and verified."},
            {"type": "final", "content": "Everything is done and verified."},
            {"type": "final", "content": "Everything is done and verified."},
        ]

        class FakeResponse:
            def __init__(self, action):
                self.action = action

            def raise_for_status(self):
                return None

            def json(self):
                return {"message": {"content": json.dumps(self.action)}}

        class FakeClient:
            def __init__(self, **_kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            async def post(self, *_args, **_kwargs):
                return FakeResponse(actions.pop(0))

        events = []
        with patch.object(agent.httpx, "AsyncClient", FakeClient):
            stream = agent.agent_stream(
                root=self.root,
                conversation_id=self.conversation_id,
                messages=[{"role": "user", "content": "Create a file"}],
                turn_id="unverified-turn",
                register_approval=main._register_approval,
                clear_approval=main._clear_approval,
                authorize_approval=main._authorize_approval,
                complete_approval=main._complete_approval,
                record_activity=database.record_agent_activity,
                task_id=task_id,
            )
            async for line in stream:
                event = json.loads(line)
                events.append(event)
                if event["type"] == "approval_required":
                    await main.decide_agent_approval(
                        event["approval_id"],
                        main.ApprovalRequest(
                            approved=True,
                            action_digest=event["action_digest"],
                        ),
                    )

        self.assertTrue((self.root / "new.txt").exists())
        self.assertEqual(database.get_agent_task(task_id)["state"], "blocked")
        self.assertEqual(database.get_agent_task(task_id)["verification_status"], "pending")
        self.assertTrue(any(event["type"] == "blocked" for event in events))
        self.assertFalse(any(event["type"] == "final" for event in events))
        with database.get_connection() as connection:
            saved = connection.execute(
                "SELECT 1 FROM messages WHERE client_message_id = ?",
                ("unverified-turn:assistant",),
            ).fetchone()
        self.assertIsNone(saved)

    async def test_denied_approval_blocks_write_and_task(self):
        task_id = "denied-write-task"
        database.create_agent_task(
            task_id,
            self.conversation_id,
            "Change the sample file",
            str(self.root),
        )
        action = {
            "type": "tool_call",
            "tool": "write_file",
            "arguments": {"path": "sample.txt", "content": "not allowed\n"},
        }

        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {"message": {"content": json.dumps(action)}}

        class FakeClient:
            def __init__(self, **_kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            async def post(self, *_args, **_kwargs):
                return FakeResponse()

        events = []
        with patch.object(agent.httpx, "AsyncClient", FakeClient):
            stream = agent.agent_stream(
                root=self.root,
                conversation_id=self.conversation_id,
                messages=[{"role": "user", "content": "Change sample"}],
                turn_id="denied-write-turn",
                register_approval=main._register_approval,
                clear_approval=main._clear_approval,
                authorize_approval=main._authorize_approval,
                complete_approval=main._complete_approval,
                record_activity=database.record_agent_activity,
                task_id=task_id,
            )
            async for line in stream:
                event = json.loads(line)
                events.append(event)
                if event["type"] == "approval_required":
                    await main.decide_agent_approval(
                        event["approval_id"],
                        main.ApprovalRequest(
                            approved=False,
                            action_digest=event["action_digest"],
                        ),
                    )

        self.assertEqual((self.root / "sample.txt").read_text(encoding="utf-8"), "before\n")
        self.assertEqual(database.get_agent_task(task_id)["state"], "blocked")
        self.assertTrue(any(event["type"] == "blocked" for event in events))
        self.assertFalse(any(event["type"] == "final" for event in events))

    async def test_task_cannot_run_verification_before_implementing_requested_change(self):
        task_id = "verify-before-write"
        database.create_agent_task(
            task_id,
            self.conversation_id,
            "Build a project feature",
            str(self.root),
        )
        action = {
            "type": "tool_call",
            "tool": "run_command",
            "arguments": {"command": "npm test"},
        }
        responses = [
            {"message": {"content": json.dumps(action)}}
            for _ in range(4)
        ]

        class FakeResponse:
            def __init__(self, value):
                self.value = value

            def raise_for_status(self):
                return None

            def json(self):
                return self.value

        class FakeClient:
            def __init__(self, **_kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            async def post(self, *_args, **_kwargs):
                return FakeResponse(responses.pop(0))

        with patch.object(agent.httpx, "AsyncClient", FakeClient):
            events = [
                json.loads(line)
                async for line in agent.agent_stream(
                    root=self.root,
                    conversation_id=self.conversation_id,
                    messages=[{"role": "user", "content": "Build a project feature"}],
                    turn_id="verify-before-write",
                    register_approval=main._register_approval,
                    clear_approval=main._clear_approval,
                    authorize_approval=main._authorize_approval,
                    complete_approval=main._complete_approval,
                    record_activity=database.record_agent_activity,
                    task_id=task_id,
                )
            ]

        self.assertEqual(database.get_agent_task(task_id)["state"], "blocked")
        self.assertFalse(any(event["type"] == "approval_required" for event in events))
        self.assertFalse(any(event["type"] == "tool_start" for event in events))
        self.assertTrue(any(event["type"] == "blocked" for event in events))


if __name__ == "__main__":
    unittest.main()
