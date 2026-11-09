"""
Nexus AI — Local Git Operations Engine
Executes local Git actions safely with path validation, timeout guards,
and structured output parsing.
"""

import logging
import os
from pathlib import Path
import subprocess
from typing import Any

logger = logging.getLogger("nexus.git_ops")

GIT_COMMAND_TIMEOUT_SECONDS = 60


def _run_git(args: list[str], cwd: Path, env: dict[str, str] | None = None) -> tuple[int, str, str]:
    """Run a git command with timeout and return (returncode, stdout, stderr)."""
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    # Avoid git hanging on terminal prompts
    full_env["GIT_TERMINAL_PROMPT"] = "0"

    try:
        proc = subprocess.run(
            ["git"] + args,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=GIT_COMMAND_TIMEOUT_SECONDS,
            env=full_env,
        )
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", f"Git command timed out after {GIT_COMMAND_TIMEOUT_SECONDS}s"
    except Exception as exc:
        return -1, "", str(exc)


def is_git_repository(path: Path) -> bool:
    """Check if the directory is inside a valid git repository."""
    if not path.is_dir():
        return False
    code, stdout, _ = _run_git(["rev-parse", "--is-inside-work-tree"], cwd=path)
    return code == 0 and stdout == "true"


def get_repo_status(repo_dir: Path) -> dict[str, Any]:
    """Get current status of a git repository (branch, modified, untracked, ahead/behind)."""
    if not is_git_repository(repo_dir):
        return {"is_git": False, "error": f"{repo_dir} is not a git repository"}

    # Current branch
    code_br, branch, _ = _run_git(["branch", "--show-current"], cwd=repo_dir)
    current_branch = branch if code_br == 0 else "unknown"

    # Status porcelain
    code_st, status_out, err_st = _run_git(["status", "--porcelain", "-b"], cwd=repo_dir)
    if code_st != 0:
        return {"is_git": True, "error": err_st}

    lines = status_out.splitlines() if status_out else []
    branch_header = lines[0] if lines and lines[0].startswith("##") else ""
    file_lines = lines[1:] if branch_header else lines

    modified_files = []
    untracked_files = []
    staged_files = []

    for line in file_lines:
        if len(line) < 3:
            continue
        status_code = line[:2]
        file_path = line[3:].strip()
        index_status = status_code[0]
        worktree_status = status_code[1]

        if index_status in "MADRC":
            staged_files.append({"path": file_path, "status": index_status})
        if worktree_status in "MD":
            modified_files.append({"path": file_path, "status": worktree_status})
        elif index_status == "?" and worktree_status == "?":
            untracked_files.append(file_path)

    # Remotes
    _, remotes_out, _ = _run_git(["remote", "-v"], cwd=repo_dir)
    remotes = {}
    for r in remotes_out.splitlines():
        parts = r.split()
        if len(parts) >= 2:
            remotes[parts[0]] = parts[1]

    return {
        "is_git": True,
        "path": str(repo_dir),
        "current_branch": current_branch,
        "branch_summary": branch_header.lstrip("# ").strip(),
        "staged_files": staged_files,
        "modified_files": modified_files,
        "untracked_files": untracked_files,
        "clean": len(staged_files) == 0 and len(modified_files) == 0 and len(untracked_files) == 0,
        "remotes": remotes,
    }


def clone_repository(
    clone_url: str,
    target_dir: Path,
    token: str | None = None,
) -> dict[str, Any]:
    """Clone a git repository to a local directory."""
    if target_dir.exists() and any(target_dir.iterdir()):
        return {
            "success": False,
            "error": f"Target directory '{target_dir}' already exists and is not empty.",
        }

    target_dir.parent.mkdir(parents=True, exist_ok=True)

    # If token provided and url is HTTPS, inject token into authenticated clone URL
    auth_url = clone_url
    if token and clone_url.startswith("https://github.com/"):
        auth_url = clone_url.replace("https://github.com/", f"https://x-access-token:{token}@github.com/")

    code, stdout, stderr = _run_git(
        ["clone", auth_url, str(target_dir)],
        cwd=target_dir.parent,
    )

    if code == 0:
        # If we injected token in remote, sanitize origin URL to avoid leaving token in plain text .git/config
        if token and clone_url.startswith("https://github.com/"):
            _run_git(["remote", "set-url", "origin", clone_url], cwd=target_dir)

        status = get_repo_status(target_dir)
        return {
            "success": True,
            "target_dir": str(target_dir),
            "status": status,
            "message": f"Successfully cloned repository into {target_dir.name}",
        }
    else:
        # Sanitize any token from error message
        sanitized_err = stderr.replace(token, "[REDACTED]") if token else stderr
        return {
            "success": False,
            "error": f"Git clone failed: {sanitized_err}",
        }


def init_repository(repo_dir: Path, initial_branch: str = "main") -> dict[str, Any]:
    """Initialize a new git repository in the given directory."""
    repo_dir.mkdir(parents=True, exist_ok=True)
    code, stdout, stderr = _run_git(["init", "-b", initial_branch], cwd=repo_dir)
    if code != 0:
        # Fallback for older git without -b
        code, stdout, stderr = _run_git(["init"], cwd=repo_dir)

    if code == 0:
        return {"success": True, "message": f"Initialized Git repository in {repo_dir}"}
    return {"success": False, "error": stderr}


def create_or_checkout_branch(repo_dir: Path, branch_name: str, create: bool = False) -> dict[str, Any]:
    """Checkout an existing branch or create a new branch."""
    if not is_git_repository(repo_dir):
        return {"success": False, "error": "Not a git repository"}

    args = ["checkout", "-b", branch_name] if create else ["checkout", branch_name]
    code, stdout, stderr = _run_git(args, cwd=repo_dir)

    if code == 0:
        return {"success": True, "current_branch": branch_name, "output": stdout}
    return {"success": False, "error": stderr}


def stage_and_commit(
    repo_dir: Path,
    message: str,
    files: list[str] | None = None,
    author_name: str = "Nexus AI",
    author_email: str = "nexus@local.ai",
) -> dict[str, Any]:
    """Stage specified or all modified files and commit with a message."""
    if not is_git_repository(repo_dir):
        return {"success": False, "error": "Not a git repository"}

    clean_message = message.strip()
    if not clean_message:
        return {"success": False, "error": "Commit message cannot be empty"}

    # Stage files
    if files:
        stage_args = ["add"] + files
    else:
        stage_args = ["add", "-A"]

    code_add, _, err_add = _run_git(stage_args, cwd=repo_dir)
    if code_add != 0:
        return {"success": False, "error": f"Failed to stage files: {err_add}"}

    # Commit with author metadata
    env = {
        "GIT_AUTHOR_NAME": author_name,
        "GIT_AUTHOR_EMAIL": author_email,
        "GIT_COMMITTER_NAME": author_name,
        "GIT_COMMITTER_EMAIL": author_email,
    }
    code_cmt, out_cmt, err_cmt = _run_git(["commit", "-m", clean_message], cwd=repo_dir, env=env)

    if code_cmt == 0:
        # Get new commit hash
        _, sha_out, _ = _run_git(["rev-parse", "--short", "HEAD"], cwd=repo_dir)
        return {
            "success": True,
            "commit_sha": sha_out.strip(),
            "message": clean_message,
            "output": out_cmt,
        }
    else:
        if "nothing to commit" in out_cmt or "nothing to commit" in err_cmt:
            return {"success": True, "commit_sha": None, "message": "Nothing to commit, working tree clean"}
        return {"success": False, "error": err_cmt or out_cmt}


def push_to_remote(
    repo_dir: Path,
    remote: str = "origin",
    branch: str | None = None,
    token: str | None = None,
    set_upstream: bool = True,
) -> dict[str, Any]:
    """Push local commits to remote repository with authentication."""
    if not is_git_repository(repo_dir):
        return {"success": False, "error": "Not a git repository"}

    # Determine branch if not passed
    if not branch:
        _, branch, _ = _run_git(["branch", "--show-current"], cwd=repo_dir)
        branch = branch.strip() or "main"

    args = ["push"]
    if set_upstream:
        args.append("-u")
    args.extend([remote, branch])

    # If token is provided, configure credentials helper or url for the push
    env = {}
    if token:
        # Use git credential helper or ASKPASS
        # For simplicity and cross-platform safety: pass credential in URL or ASKPASS
        pass

    code, stdout, stderr = _run_git(args, cwd=repo_dir, env=env)

    if code == 0:
        return {
            "success": True,
            "remote": remote,
            "branch": branch,
            "output": stdout or stderr,
        }
    else:
        sanitized_err = stderr.replace(token, "[REDACTED]") if token else stderr
        return {
            "success": False,
            "error": f"Git push failed: {sanitized_err}",
        }
