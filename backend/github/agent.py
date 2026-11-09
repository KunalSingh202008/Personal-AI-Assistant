"""
Nexus AI — GitHub Autonomous Agent
Coordinates natural language requests for repository discovery, code inspection,
branching, committing, pushing, and repository creation.
"""

import logging
from pathlib import Path
from typing import Any

from .client import GitHubClient, get_stored_github_token
from .git_ops import (
    clone_repository,
    create_or_checkout_branch,
    get_repo_status,
    init_repository,
    is_git_repository,
    push_to_remote,
    stage_and_commit,
)

logger = logging.getLogger("nexus.github_agent")


class GitHubAgent:
    def __init__(self, token: str | None = None, workspace_path: str = "."):
        self.client = GitHubClient(token)
        self.workspace_path = Path(workspace_path).resolve()

    async def get_status(self) -> dict[str, Any]:
        """Check authentication status and current workspace git status."""
        auth_status = await self.client.verify_token()
        workspace_git = get_repo_status(self.workspace_path)
        return {
            "github_auth": auth_status,
            "workspace_git": workspace_git,
        }

    async def find_repository(self, name_or_query: str) -> dict[str, Any]:
        """Find a repository by exact name or search query."""
        repos = await self.client.list_repositories()
        exact = [r for r in repos if r["name"].lower() == name_or_query.lower() or r["full_name"].lower() == name_or_query.lower()]
        if exact:
            return {"match_type": "exact", "repository": exact[0]}

        matches = [r for r in repos if name_or_query.lower() in r["name"].lower()]
        if matches:
            return {"match_type": "partial", "matches": matches}

        # Fallback to search API
        search_res = await self.client.search_repositories(name_or_query)
        return {"match_type": "search", "matches": search_res}

    async def inspect_repository(self, owner: str, repo: str) -> dict[str, Any]:
        """Deeply inspect a GitHub repository: metadata, file tree, branches, commits, PRs."""
        repo_data = await self.client.get_repository(owner, repo)
        branches = await self.client.list_branches(owner, repo)
        commits = await self.client.list_commits(owner, repo, limit=10)
        pulls = await self.client.list_pull_requests(owner, repo, state="open")
        issues = await self.client.list_issues(owner, repo, state="open")
        tree = await self.client.get_tree(owner, repo, branch=repo_data.get("default_branch", "main"))

        # Look for README
        readme_file = next((f for f in tree if f["path"].lower().startswith("readme")), None)
        readme_content = ""
        if readme_file:
            try:
                readme_content = await self.client.get_file_content(owner, repo, readme_file["path"])
            except Exception as e:
                logger.warning(f"Could not fetch README for {owner}/{repo}: {e}")

        return {
            "repository": repo_data,
            "branches": branches,
            "recent_commits": commits,
            "open_pull_requests": pulls,
            "open_issues": issues,
            "total_files": len(tree),
            "file_tree": tree[:500],  # bounded
            "readme_preview": readme_content[:4000],
        }

    def clone_to_workspace(self, clone_url: str, directory_name: str) -> dict[str, Any]:
        """Clone a repository into a subdirectory of the current workspace."""
        target_dir = self.workspace_path / directory_name
        return clone_repository(clone_url, target_dir, token=self.client.token)

    def commit_workspace(self, message: str, files: list[str] | None = None) -> dict[str, Any]:
        """Commit changes in the current workspace git repository."""
        return stage_and_commit(self.workspace_path, message, files=files)

    def push_workspace(self, remote: str = "origin", branch: str | None = None) -> dict[str, Any]:
        """Push workspace commits to remote."""
        return push_to_remote(self.workspace_path, remote=remote, branch=branch, token=self.client.token)
