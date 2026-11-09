import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

import database
from database import initialize_database, set_setting
from github.client import GitHubClient, get_stored_github_token, save_github_token
from github.git_ops import (
    create_or_checkout_branch,
    get_repo_status,
    init_repository,
    is_git_repository,
    stage_and_commit,
)
from github.agent import GitHubAgent


class GitHubModuleTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.db_path = Path(cls.temp_dir.name) / "test_github.db"
        cls.db_patch = patch.object(database, "DATABASE_PATH", cls.db_path)
        cls.db_patch.start()
        initialize_database()

    @classmethod
    def tearDownClass(cls):
        cls.db_patch.stop()
        cls.temp_dir.cleanup()

    def test_token_storage(self):
        save_github_token("ghp_test_token_1234567890")
        self.assertEqual(get_stored_github_token(), "ghp_test_token_1234567890")

    async def test_client_verify_token_mocked(self):
        fake_user = {
            "login": "kunalsingh",
            "name": "Kunal Singh",
            "avatar_url": "https://avatars.githubusercontent.com/u/123",
            "html_url": "https://github.com/kunalsingh",
            "public_repos": 12,
            "total_private_repos": 5,
        }

        class FakeResponse:
            def __init__(self, status_code, data):
                self.status_code = status_code
                self._data = data

            def json(self):
                return self._data

            def raise_for_status(self):
                if self.status_code >= 400:
                    raise Exception(f"HTTP {self.status_code}")

        class FakeAsyncClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            async def get(self, url, headers=None, params=None):
                if "/user" in url and not url.endswith("/user/repos"):
                    return FakeResponse(200, fake_user)
                elif "/user/repos" in url:
                    return FakeResponse(200, [
                        {
                            "id": 1,
                            "name": "NexusAI",
                            "full_name": "kunalsingh/NexusAI",
                            "owner": {"login": "kunalsingh"},
                            "private": True,
                            "html_url": "https://github.com/kunalsingh/NexusAI",
                            "clone_url": "https://github.com/kunalsingh/NexusAI.git",
                            "default_branch": "main",
                        }
                    ])
                return FakeResponse(404, {})

        with patch("github.client.httpx.AsyncClient", FakeAsyncClient):
            client = GitHubClient("fake_token")
            verified = await client.verify_token()
            self.assertTrue(verified["authenticated"])
            self.assertEqual(verified["login"], "kunalsingh")

            repos = await client.list_repositories()
            self.assertEqual(len(repos), 1)
            self.assertEqual(repos[0]["name"], "NexusAI")

    def test_local_git_operations_lifecycle(self):
        """Test real local git operations using temporary directory."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_path = Path(tmp_dir) / "test_git_repo"

            # 1. Not a repo initially
            self.assertFalse(is_git_repository(repo_path))

            # 2. Initialize repo
            init_res = init_repository(repo_path, initial_branch="main")
            self.assertTrue(init_res["success"])
            self.assertTrue(is_git_repository(repo_path))

            # 3. Check clean status
            status = get_repo_status(repo_path)
            self.assertTrue(status["is_git"])
            self.assertTrue(status["clean"])

            # 4. Create and stage a file
            test_file = repo_path / "hello.txt"
            test_file.write_text("Hello Nexus AI Operating System", encoding="utf-8")

            status_mod = get_repo_status(repo_path)
            self.assertFalse(status_mod["clean"])
            self.assertIn("hello.txt", status_mod["untracked_files"])

            # 5. Commit file
            commit_res = stage_and_commit(repo_path, "Initial commit from Nexus")
            self.assertTrue(commit_res["success"])
            self.assertIsNotNone(commit_res["commit_sha"])

            # 6. Working tree should be clean after commit
            status_after = get_repo_status(repo_path)
            self.assertTrue(status_after["clean"])

            # 7. Create and switch to new branch
            branch_res = create_or_checkout_branch(repo_path, "feature-orchestrator", create=True)
            self.assertTrue(branch_res["success"])
            self.assertEqual(branch_res["current_branch"], "feature-orchestrator")


if __name__ == "__main__":
    unittest.main()
