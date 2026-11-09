"""
Nexus AI — GitHub API Integration Client
Provides authenticated access to GitHub REST API for repository discovery,
inspection, branch management, issue tracking, and repository creation.
"""

import logging
from typing import Any
import httpx

from database import get_setting, set_setting

logger = logging.getLogger("nexus.github")

GITHUB_API_BASE = "https://api.github.com"
GITHUB_TOKEN_SETTING_KEY = "github_personal_access_token"
GITHUB_USER_SETTING_KEY = "github_authenticated_user"


def get_stored_github_token() -> str | None:
    return get_setting(GITHUB_TOKEN_SETTING_KEY)


def save_github_token(token: str) -> None:
    set_setting(GITHUB_TOKEN_SETTING_KEY, token.strip())


def delete_github_token() -> None:
    set_setting(GITHUB_TOKEN_SETTING_KEY, "")
    set_setting(GITHUB_USER_SETTING_KEY, "")


class GitHubClient:
    def __init__(self, token: str | None = None):
        self.token = token or get_stored_github_token() or ""

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "NexusAI-OperatingSystem/1.0",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    async def verify_token(self) -> dict[str, Any]:
        """Verify the GitHub token and return the authenticated user profile."""
        if not self.token:
            return {"authenticated": False, "error": "No GitHub token configured"}

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{GITHUB_API_BASE}/user", headers=self._headers())
            if resp.status_code == 200:
                user_data = resp.json()
                # Cache user info
                set_setting(GITHUB_USER_SETTING_KEY, user_data.get("login", ""))
                return {
                    "authenticated": True,
                    "login": user_data.get("login"),
                    "name": user_data.get("name"),
                    "avatar_url": user_data.get("avatar_url"),
                    "html_url": user_data.get("html_url"),
                    "public_repos": user_data.get("public_repos", 0),
                    "total_private_repos": user_data.get("total_private_repos", 0),
                }
            elif resp.status_code == 401:
                return {"authenticated": False, "error": "Invalid or expired GitHub token"}
            else:
                return {"authenticated": False, "error": f"GitHub API returned HTTP {resp.status_code}"}

    async def list_repositories(
        self,
        sort: str = "updated",
        direction: str = "desc",
        per_page: int = 30,
        page: int = 1,
    ) -> list[dict[str, Any]]:
        """List repositories for the authenticated user."""
        if not self.token:
            raise ValueError("GitHub authentication required. Please connect your GitHub account.")

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{GITHUB_API_BASE}/user/repos",
                headers=self._headers(),
                params={
                    "sort": sort,
                    "direction": direction,
                    "per_page": min(per_page, 100),
                    "page": page,
                    "affiliation": "owner,collaborator,organization_member",
                },
            )
            resp.raise_for_status()
            repos = resp.json()
            return [self._format_repo(r) for r in repos]

    async def search_repositories(self, query: str, per_page: int = 20) -> list[dict[str, Any]]:
        """Search GitHub repositories by keyword."""
        clean_query = query.strip()
        if not clean_query:
            return []

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{GITHUB_API_BASE}/search/repositories",
                headers=self._headers(),
                params={"q": clean_query, "per_page": min(per_page, 50)},
            )
            resp.raise_for_status()
            data = resp.json()
            return [self._format_repo(r) for r in data.get("items", [])]

    async def get_repository(self, owner: str, repo: str) -> dict[str, Any]:
        """Fetch detailed metadata for a specific repository."""
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{GITHUB_API_BASE}/repos/{owner}/{repo}",
                headers=self._headers(),
            )
            resp.raise_for_status()
            return self._format_repo(resp.json())

    async def get_tree(
        self,
        owner: str,
        repo: str,
        branch: str = "HEAD",
        recursive: bool = True,
    ) -> list[dict[str, Any]]:
        """Fetch the git tree (file hierarchy) of a repository."""
        async with httpx.AsyncClient(timeout=20.0) as client:
            # 1. Resolve branch to tree sha
            ref_resp = await client.get(
                f"{GITHUB_API_BASE}/repos/{owner}/{repo}/commits/{branch}",
                headers=self._headers(),
            )
            ref_resp.raise_for_status()
            commit_data = ref_resp.json()
            tree_sha = commit_data.get("commit", {}).get("tree", {}).get("sha")
            if not tree_sha:
                return []

            params = {"recursive": "1"} if recursive else {}
            tree_resp = await client.get(
                f"{GITHUB_API_BASE}/repos/{owner}/{repo}/git/trees/{tree_sha}",
                headers=self._headers(),
                params=params,
            )
            tree_resp.raise_for_status()
            tree_data = tree_resp.json()

            items = []
            for item in tree_data.get("tree", []):
                items.append({
                    "path": item.get("path"),
                    "mode": item.get("mode"),
                    "type": "dir" if item.get("type") == "tree" else "file",
                    "size": item.get("size", 0),
                    "sha": item.get("sha"),
                })
            return items

    async def get_file_content(
        self,
        owner: str,
        repo: str,
        path: str,
        branch: str = "HEAD",
    ) -> str:
        """Fetch the raw text content of a file from a repository."""
        import base64

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{GITHUB_API_BASE}/repos/{owner}/{repo}/contents/{path}",
                headers=self._headers(),
                params={"ref": branch},
            )
            resp.raise_for_status()
            data = resp.json()
            encoding = data.get("encoding", "")
            content = data.get("content", "")
            if encoding == "base64":
                return base64.b64decode(content).decode("utf-8", errors="replace")
            return content

    async def list_branches(self, owner: str, repo: str) -> list[dict[str, Any]]:
        """List branches for a repository."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{GITHUB_API_BASE}/repos/{owner}/{repo}/branches",
                headers=self._headers(),
            )
            resp.raise_for_status()
            return [
                {
                    "name": b.get("name"),
                    "protected": b.get("protected", False),
                    "commit_sha": b.get("commit", {}).get("sha"),
                }
                for b in resp.json()
            ]

    async def list_commits(self, owner: str, repo: str, limit: int = 15) -> list[dict[str, Any]]:
        """List recent commits on a repository."""
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{GITHUB_API_BASE}/repos/{owner}/{repo}/commits",
                headers=self._headers(),
                params={"per_page": limit},
            )
            resp.raise_for_status()
            results = []
            for c in resp.json():
                commit_info = c.get("commit", {})
                author = commit_info.get("author", {})
                results.append({
                    "sha": c.get("sha", "")[:7],
                    "full_sha": c.get("sha", ""),
                    "message": commit_info.get("message", "").split("\n")[0],
                    "author": author.get("name", ""),
                    "date": author.get("date", ""),
                    "html_url": c.get("html_url", ""),
                })
            return results

    async def list_pull_requests(
        self,
        owner: str,
        repo: str,
        state: str = "open",
    ) -> list[dict[str, Any]]:
        """List pull requests for a repository."""
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{GITHUB_API_BASE}/repos/{owner}/{repo}/pulls",
                headers=self._headers(),
                params={"state": state, "per_page": 20},
            )
            resp.raise_for_status()
            return [
                {
                    "number": pr.get("number"),
                    "title": pr.get("title"),
                    "state": pr.get("state"),
                    "user": pr.get("user", {}).get("login"),
                    "html_url": pr.get("html_url"),
                    "created_at": pr.get("created_at"),
                }
                for pr in resp.json()
            ]

    async def list_issues(self, owner: str, repo: str, state: str = "open") -> list[dict[str, Any]]:
        """List issues for a repository."""
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{GITHUB_API_BASE}/repos/{owner}/{repo}/issues",
                headers=self._headers(),
                params={"state": state, "per_page": 20},
            )
            resp.raise_for_status()
            # GitHub issues endpoint includes pull requests, filter them out
            issues = [i for i in resp.json() if "pull_request" not in i]
            return [
                {
                    "number": issue.get("number"),
                    "title": issue.get("title"),
                    "state": issue.get("state"),
                    "user": issue.get("user", {}).get("login"),
                    "html_url": issue.get("html_url"),
                    "comments": issue.get("comments", 0),
                    "created_at": issue.get("created_at"),
                }
                for issue in issues
            ]

    async def create_repository(
        self,
        name: str,
        description: str = "",
        private: bool = True,
        auto_init: bool = True,
    ) -> dict[str, Any]:
        """Create a new repository under the authenticated user's account."""
        if not self.token:
            raise ValueError("GitHub authentication required to create repositories.")

        payload = {
            "name": name.strip(),
            "description": description.strip(),
            "private": private,
            "auto_init": auto_init,
        }

        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                f"{GITHUB_API_BASE}/user/repos",
                headers=self._headers(),
                json=payload,
            )
            resp.raise_for_status()
            return self._format_repo(resp.json())

    def _format_repo(self, repo: dict[str, Any]) -> dict[str, Any]:
        owner = repo.get("owner", {})
        return {
            "id": repo.get("id"),
            "name": repo.get("name"),
            "full_name": repo.get("full_name"),
            "owner": owner.get("login"),
            "owner_avatar": owner.get("avatar_url"),
            "description": repo.get("description") or "",
            "private": repo.get("private", False),
            "html_url": repo.get("html_url"),
            "clone_url": repo.get("clone_url"),
            "ssh_url": repo.get("ssh_url"),
            "default_branch": repo.get("default_branch", "main"),
            "stargazers_count": repo.get("stargazers_count", 0),
            "forks_count": repo.get("forks_count", 0),
            "open_issues_count": repo.get("open_issues_count", 0),
            "language": repo.get("language") or "",
            "updated_at": repo.get("updated_at"),
            "created_at": repo.get("created_at"),
        }
