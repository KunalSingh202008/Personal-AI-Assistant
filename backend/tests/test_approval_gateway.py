import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

import database
import main
from action_policy import action_digest


class ApprovalGatewayTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.database_patch = patch.object(
            database, "DATABASE_PATH", self.root / "test.db"
        )
        self.database_patch.start()
        database.initialize_database()
        main.APPROVALS.clear()

    async def asyncTearDown(self):
        main.APPROVALS.clear()
        self.database_patch.stop()
        self.temporary.cleanup()

    def create_ticket(self, approval_id="approval-test"):
        arguments = {
            "path": "sample.py",
            "content": "password=NEVER_STORE_THIS",
            "expected_sha256": None,
        }
        workspace = str(self.root)
        digest = action_digest("write_file", arguments, workspace)
        future = main._register_approval(
            approval_id,
            {
                "action": "write_file",
                "arguments": arguments,
                "workspace": workspace,
                "action_digest": digest,
                "risk": "AMBER",
                "target": "sample.py",
                "purpose": "Create or edit a workspace file.",
                "reversible": True,
                "alternatives": "Deny the request.",
            },
        )
        return future, arguments, digest

    async def test_digest_mismatch_cannot_approve_pending_action(self):
        future, _arguments, digest = self.create_ticket()
        with self.assertRaises(HTTPException) as raised:
            await main.decide_agent_approval(
                "approval-test",
                main.ApprovalRequest(
                    approved=True,
                    action_digest="0" * 64,
                ),
            )
        self.assertEqual(raised.exception.status_code, 409)
        self.assertFalse(future.done())
        self.assertEqual(main.APPROVALS["approval-test"].status, "pending")
        self.assertEqual(len(digest), 64)

    async def test_exact_approval_is_rechecked_before_execution(self):
        future, arguments, digest = self.create_ticket()
        await main.decide_agent_approval(
            "approval-test",
            main.ApprovalRequest(approved=True, action_digest=digest),
        )
        self.assertTrue(future.result())
        altered = {**arguments, "content": "different content"}
        self.assertFalse(
            main._authorize_approval(
                "approval-test",
                digest,
                "write_file",
                altered,
                self.root,
            )
        )
        self.assertEqual(main.APPROVALS["approval-test"].status, "mismatched")

    async def test_denial_and_expiration_never_authorize_execution(self):
        denied_future, _args, denied_digest = self.create_ticket("denied")
        await main.decide_agent_approval(
            "denied",
            main.ApprovalRequest(
                approved=False,
                action_digest=denied_digest,
            ),
        )
        self.assertFalse(denied_future.result())
        self.assertEqual(main.APPROVALS["denied"].status, "denied")

        expired_future, _args, expired_digest = self.create_ticket("expired")
        main.APPROVALS["expired"].expires_at = time.monotonic() - 1
        with self.assertRaises(HTTPException) as raised:
            await main.decide_agent_approval(
                "expired",
                main.ApprovalRequest(
                    approved=True,
                    action_digest=expired_digest,
                ),
            )
        self.assertEqual(raised.exception.status_code, 410)
        self.assertFalse(expired_future.result())
        self.assertEqual(main.APPROVALS["expired"].status, "expired")

    async def test_cancellation_and_audit_redact_action_contents(self):
        self.create_ticket("cancelled")
        main._clear_approval("cancelled")
        events = database.list_agent_activity()
        self.assertEqual(
            [entry["event"] for entry in reversed(events)],
            ["requested", "cancelled"],
        )
        serialized = repr(events)
        self.assertNotIn("NEVER_STORE_THIS", serialized)
        self.assertNotIn("content", serialized)

    async def test_approval_is_single_use_and_audit_records_execution(self):
        future, arguments, digest = self.create_ticket()
        request = main.ApprovalRequest(approved=True, action_digest=digest)
        await main.decide_agent_approval("approval-test", request)
        with self.assertRaises(HTTPException) as raised:
            await main.decide_agent_approval("approval-test", request)
        self.assertEqual(raised.exception.status_code, 409)
        self.assertTrue(future.result())
        self.assertTrue(
            main._authorize_approval(
                "approval-test",
                digest,
                "write_file",
                arguments,
                self.root,
            )
        )
        main._complete_approval("approval-test", "executed")
        main._clear_approval("approval-test")
        events = database.list_agent_activity()
        self.assertEqual(
            [entry["event"] for entry in reversed(events)],
            ["requested", "approved", "executing", "executed"],
        )


if __name__ == "__main__":
    unittest.main()
