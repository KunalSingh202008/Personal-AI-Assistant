import hashlib
import json
from dataclasses import dataclass
from typing import Literal


RiskLevel = Literal["GREEN", "AMBER", "RED"]


@dataclass(frozen=True)
class ActionPolicy:
    risk: RiskLevel
    requires_approval: bool
    purpose: str
    reversible: bool
    alternatives: str


POLICIES = {
    "list_files": ActionPolicy(
        "GREEN", False, "Inspect workspace structure.", True, "No change is made."
    ),
    "search_workspace": ActionPolicy(
        "GREEN", False, "Find relevant workspace files or text.", True, "No change is made."
    ),
    "read_file": ActionPolicy(
        "GREEN", False, "Read a non-sensitive workspace file.", True, "No change is made."
    ),
    "git_status": ActionPolicy(
        "GREEN", False, "Inspect local Git status.", True, "No change is made."
    ),
    "git_diff": ActionPolicy(
        "GREEN", False, "Inspect the unstaged local Git diff.", True, "No change is made."
    ),
    "web_search": ActionPolicy(
        "GREEN", False, "Check whether public web search is configured.", True, "No web request is made."
    ),
    "write_file": ActionPolicy(
        "AMBER",
        True,
        "Create or edit a workspace file.",
        True,
        "Deny the request to leave the workspace unchanged.",
    ),
    "run_command": ActionPolicy(
        "AMBER",
        True,
        "Run an allowlisted verification command in the workspace.",
        True,
        "Deny the request; no command will run.",
    ),
    "start_local_server": ActionPolicy(
        "AMBER",
        True,
        "Execute the selected workspace application and expose it on loopback after its health endpoint responds.",
        False,
        "Review the application source or deny the launch.",
    ),
    "git_commit": ActionPolicy(
        "AMBER",
        True,
        "Create a local Git commit from explicitly selected workspace paths.",
        False,
        "Review or stage changes manually, or deny the request.",
    ),
}


def classify_action(action: str) -> ActionPolicy:
    return POLICIES.get(
        action,
        ActionPolicy(
            "RED",
            True,
            "This operation is not explicitly supported.",
            False,
            "Use a supported, narrowly scoped workspace tool.",
        ),
    )


def action_digest(action: str, arguments: dict, workspace: str) -> str:
    payload = json.dumps(
        {
            "action": action,
            "arguments": arguments,
            "workspace": workspace,
        },
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def audit_target(action: str, arguments: dict) -> str:
    if action == "write_file":
        return str(arguments.get("path", ""))
    if action == "run_command":
        return str(arguments.get("command", ""))
    if action == "start_local_server":
        return f"{arguments.get('script', 'app.py')}:{arguments.get('health_path', '/health')}"
    if action == "git_commit":
        paths = arguments.get("paths", [])
        return json.dumps(paths, ensure_ascii=True, separators=(",", ":"))
    return ""
