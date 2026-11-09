import asyncio
import ast
import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, Field

from action_policy import ActionPolicy, classify_action


MAX_FILE_BYTES = 1_000_000
MAX_TOOL_OUTPUT = 12_000
MAX_COMMAND_SECONDS = 60
IGNORED_DIRECTORIES = {
    ".git", ".venv", "venv", "node_modules", "__pycache__", "dist", "build",
    ".ssh", ".aws", ".azure", ".gnupg",
}
SENSITIVE_NAME = re.compile(
    r"(^|[._-])(\.env|credentials?|secrets?|id_rsa|id_ed25519|"
    r"private[_-]?key|tokens?)([._-]|$)",
    re.IGNORECASE,
)
SECRET_PATTERNS = (
    re.compile(
        r"(?i)\b(api[_-]?key|access[_-]?token|password|secret)"
        r"(\s*[:=]\s*)['\"]?[^\s,'\";]+"
    ),
    re.compile(r"(?i)\b(AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9_]{20,})\b"),
    re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?"
        r"(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)",
        re.DOTALL,
    ),
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ListFilesArgs(StrictModel):
    path: str = Field(default=".", max_length=1024)
    max_depth: int = Field(default=3, ge=0, le=5)


class SearchArgs(StrictModel):
    query: str = Field(min_length=1, max_length=300)
    path: str = Field(default=".", max_length=1024)
    search_content: bool = True
    max_results: int = Field(default=30, ge=1, le=100)


class ReadFileArgs(StrictModel):
    path: str = Field(min_length=1, max_length=1024)


class WriteFileArgs(StrictModel):
    path: str = Field(min_length=1, max_length=1024)
    content: str = Field(max_length=MAX_FILE_BYTES)


class RunCommandArgs(StrictModel):
    command: Literal[
        "pytest",
        "python -m pytest",
        "python -m unittest app",
        "python -m unittest nexus_smoke_test",
        "python -m unittest nexus_smoke_test -v",
        "python -m py_compile app.py",
        "npm test",
        "npm run build",
        "npm run lint",
        "ruff check",
        "ruff format --check",
    ]


class GitCommitArgs(StrictModel):
    paths: list[str] = Field(min_length=1, max_length=50)
    message: str = Field(min_length=1, max_length=200)


class StartLocalServerArgs(StrictModel):
    script: str = Field(default="app.py", min_length=1, max_length=256)
    health_path: str = Field(
        default="/health",
        pattern=r"^/[A-Za-z0-9/_-]{0,199}$",
    )


class WebSearchArgs(StrictModel):
    query: str = Field(min_length=1, max_length=300)


ARGUMENT_MODELS = {
    "list_files": ListFilesArgs,
    "search_workspace": SearchArgs,
    "read_file": ReadFileArgs,
    "write_file": WriteFileArgs,
    "run_command": RunCommandArgs,
    "git_status": StrictModel,
    "git_diff": StrictModel,
    "git_commit": GitCommitArgs,
    "start_local_server": StartLocalServerArgs,
    "web_search": WebSearchArgs,
}

TOOL_SCHEMAS = [
    {
        "name": "list_files",
        "description": "List non-sensitive files under the selected workspace.",
        "parameters": ListFilesArgs.model_json_schema(),
    },
    {
        "name": "search_workspace",
        "description": "Search file names and optionally text in non-sensitive files.",
        "parameters": SearchArgs.model_json_schema(),
    },
    {
        "name": "read_file",
        "description": "Read a workspace file up to 1 MB; sensitive files are blocked.",
        "parameters": ReadFileArgs.model_json_schema(),
    },
    {
        "name": "write_file",
        "description": "Propose a file creation or edit. User approval is required.",
        "parameters": WriteFileArgs.model_json_schema(),
    },
    {
        "name": "run_command",
        "description": "Run one allowlisted test/build/lint command; approval is required.",
        "parameters": RunCommandArgs.model_json_schema(),
    },
    {
        "name": "git_status",
        "description": "Inspect Git status in the selected workspace.",
        "parameters": StrictModel.model_json_schema(),
    },
    {
        "name": "git_diff",
        "description": "Inspect the current unstaged Git diff in the selected workspace.",
        "parameters": StrictModel.model_json_schema(),
    },
    {
        "name": "git_commit",
        "description": "Commit explicitly selected workspace paths; user approval is required. Only use when requested.",
        "parameters": GitCommitArgs.model_json_schema(),
    },
    {
        "name": "start_local_server",
        "description": (
            "Start a Python app script inside the selected workspace, bind it to "
            "127.0.0.1 using NEXUS_HOST/NEXUS_PORT, and return a URL only after "
            "the configured health path returns HTTP 200. User approval is required."
        ),
        "parameters": StartLocalServerArgs.model_json_schema(),
    },
    {
        "name": "web_search",
        "description": "Search public web pages only if configured; otherwise reports that the provider is unavailable.",
        "parameters": WebSearchArgs.model_json_schema(),
    },
]


class ToolValidationError(ValueError):
    pass


class ApprovalRequired(Exception):
    def __init__(
        self,
        action: str,
        detail: str,
        diff: str = "",
        arguments: dict | None = None,
        policy: ActionPolicy | None = None,
    ):
        super().__init__(detail)
        self.action = action
        self.detail = detail
        self.diff = diff
        self.arguments = arguments or {}
        self.policy = policy or classify_action(action)


def validate_tool_call(name: str, arguments: object) -> BaseModel:
    model = ARGUMENT_MODELS.get(name)
    if model is None:
        raise ToolValidationError(f"Tool is not allowed: {name}")
    if not isinstance(arguments, dict):
        raise ToolValidationError("Tool arguments must be a JSON object")
    try:
        return model.model_validate(arguments)
    except Exception as exc:
        raise ToolValidationError(f"Invalid arguments for {name}: {exc}") from exc


def _within(root: Path, target: Path) -> bool:
    try:
        target.relative_to(root)
        return True
    except ValueError:
        return False


def resolve_workspace_path(root: Path, relative: str, *, allow_root: bool = True) -> Path:
    base = root.resolve(strict=True)
    candidate = (base / relative).resolve(strict=False)
    if not _within(base, candidate) or (not allow_root and candidate == base):
        raise ToolValidationError("Path must remain inside the selected workspace")
    return candidate


def _sensitive(path: Path) -> bool:
    sensitive_extensions = {
        ".pem", ".key", ".p12", ".pfx", ".kdbx", ".db", ".sqlite", ".sqlite3",
        ".db-wal", ".db-shm", ".sqlite-wal", ".sqlite-shm",
    }
    return any(
        SENSITIVE_NAME.search(part) or Path(part).suffix.casefold() in sensitive_extensions
        for part in path.parts
    )


def _redact(text: str) -> str:
    for pattern in SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text


def _validate_generated_content(path: Path, content: str) -> None:
    suffix = path.suffix.casefold()
    if suffix == ".py":
        try:
            ast.parse(content, filename=path.name)
        except SyntaxError as exc:
            location = (
                f"line {exc.lineno}, column {exc.offset}"
                if exc.lineno is not None
                else "unknown location"
            )
            source_line = (exc.text or "").strip()[:180]
            source_context = (
                f" Offending source line: {source_line!r}."
                if source_line
                else ""
            )
            raise ToolValidationError(
                f"Generated Python has a syntax error at {location}: {exc.msg}. "
                f"{source_context} Correct the source before requesting write approval."
            ) from exc
    elif suffix == ".json":
        try:
            json.loads(content)
        except json.JSONDecodeError as exc:
            lines = content.splitlines()
            source_line = (
                lines[exc.lineno - 1].strip()[:180]
                if exc.lineno <= len(lines)
                else ""
            )
            source_context = (
                f" Invalid source line: {source_line!r}."
                if source_line
                else ""
            )
            raise ToolValidationError(
                f"Generated JSON is invalid at line {exc.lineno}, "
                f"column {exc.colno}: {exc.msg}.{source_context} "
                "Correct it before approval."
            ) from exc


def _bounded(text: str) -> str:
    if len(text) > MAX_TOOL_OUTPUT:
        return text[:MAX_TOOL_OUTPUT] + "\n[Output truncated]"
    return text


def _kill_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is None:
        try:
            process.kill()
        except OSError:
            pass


def _capture_output(
    process: subprocess.Popen[bytes],
    captured: bytearray,
    truncated: threading.Event,
    failures: list[str],
) -> None:
    if process.stdout is None:
        return
    try:
        while chunk := process.stdout.read(8192):
            available = MAX_TOOL_OUTPUT - len(captured)
            if available > 0:
                captured.extend(chunk[:available])
            if len(chunk) > available and not truncated.is_set():
                truncated.set()
                _kill_process(process)
    except OSError as exc:
        failures.append(exc.strerror or "Could not capture command output")
        _kill_process(process)


async def _run_process(
    arguments: list[str],
    working_directory: Path,
) -> tuple[int, str]:
    try:
        process = subprocess.Popen(
            arguments,
            cwd=working_directory,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            shell=False,
            creationflags=(
                subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
            ),
        )
    except OSError as exc:
        raise ToolValidationError(
            f"Could not start approved command: {exc.strerror or 'process creation failed'}"
        ) from exc

    captured = bytearray()
    truncated = threading.Event()
    failures: list[str] = []
    reader = threading.Thread(
        target=_capture_output,
        args=(process, captured, truncated, failures),
        daemon=True,
    )
    reader.start()
    started = time.monotonic()
    timed_out = False
    try:
        while process.poll() is None:
            if time.monotonic() - started >= MAX_COMMAND_SECONDS:
                timed_out = True
                _kill_process(process)
                break
            await asyncio.sleep(0.05)
        await asyncio.to_thread(process.wait)
        await asyncio.to_thread(reader.join)
    except asyncio.CancelledError:
        _kill_process(process)
        await asyncio.to_thread(process.wait)
        await asyncio.to_thread(reader.join)
        raise
    finally:
        if process.stdout is not None:
            process.stdout.close()

    if timed_out:
        raise ToolValidationError(
            f"Operation exceeded its {MAX_COMMAND_SECONDS}-second timeout"
        )
    if failures:
        raise ToolValidationError(failures[0])
    output = _redact(captured.decode("utf-8", errors="replace"))
    if truncated.is_set():
        output += "\n[Output limit reached; process stopped]"
    return process.returncode or 0, output


class WorkspaceTools:
    def __init__(self, root: Path):
        self.root = root.resolve(strict=True)
        if not self.root.is_dir():
            raise ToolValidationError("Selected workspace must be a directory")

    async def execute(self, name: str, arguments: object) -> str:
        parsed = validate_tool_call(name, arguments)
        policy = classify_action(name)
        if policy.risk == "RED":
            raise ToolValidationError("This operation is blocked by workspace policy")
        if name == "list_files":
            return self._list_files(parsed)
        if name == "search_workspace":
            return self._search(parsed)
        if name == "read_file":
            return self._read_file(parsed)
        if name == "write_file":
            raise self._write_file(parsed, policy)
        if name == "run_command":
            raise ApprovalRequired(
                "run_command",
                parsed.command,
                arguments=parsed.model_dump(),
                policy=policy,
            )
        if name == "start_local_server":
            script_path, source, source_hash = self._local_server_script(
                parsed.script
            )
            raise ApprovalRequired(
                name,
                (
                    f"Run {parsed.script} in this workspace and verify "
                    f"GET {parsed.health_path} returns HTTP 200 on loopback."
                ),
                diff=_redact(source),
                arguments={
                    **parsed.model_dump(),
                    "script": str(script_path.relative_to(self.root)),
                    "expected_sha256": source_hash,
                },
                policy=policy,
            )
        if name == "git_status":
            return await self._git("status", "--short")
        if name == "git_diff":
            return await self._git("diff", "--no-ext-diff")
        if name == "git_commit":
            args = parsed
            targets = [
                str(
                    resolve_workspace_path(
                        self.root, item, allow_root=False
                    ).relative_to(self.root)
                )
                for item in args.paths
            ]
            if any(_sensitive(self.root / item) for item in targets):
                raise ToolValidationError("Committing sensitive files is not allowed")
            detail = (
                f"Commit {len(targets)} selected workspace path(s): "
                f"{args.message}"
            )
            raise ApprovalRequired(
                "git_commit",
                detail,
                arguments={"paths": targets, "message": args.message},
                policy=policy,
            )
        if name == "web_search":
            return (
                "Public web search is not configured. No web provider has been enabled, "
                "so no external request was made."
            )
        raise ToolValidationError(f"Tool is not allowed: {name}")

    async def start_approved_local_server(
        self,
        script: str,
        health_path: str,
        expected_sha256: str,
    ) -> str:
        path, _source, current_hash = self._local_server_script(script)
        if current_hash != expected_sha256:
            raise ToolValidationError(
                "Local server script changed after approval; review it and request approval again."
            )
        from local_server import start_local_server

        server_id, url = await start_local_server(
            self.root,
            str(path.relative_to(self.root)),
            health_path,
        )
        return (
            f"Health verified: GET {url}{health_path} returned HTTP 200. "
            f"Confirmed localhost URL: {url} (server id {server_id})"
        )

    def _local_server_script(self, script: str) -> tuple[Path, str, str]:
        path = resolve_workspace_path(
            self.root, script, allow_root=False
        )
        if (
            path.suffix.casefold() != ".py"
            or _sensitive(path)
            or path.is_symlink()
            or not path.is_file()
        ):
            raise ToolValidationError(
                "Local server must be an existing, non-sensitive Python file in the workspace"
            )
        if path.stat().st_size > MAX_TOOL_OUTPUT:
            raise ToolValidationError(
                "Local server source exceeds the approval preview limit; split it into smaller workspace modules."
            )
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise ToolValidationError(
                "Local server script cannot be safely read as UTF-8 text"
            ) from exc
        return path, source, hashlib.sha256(source.encode("utf-8")).hexdigest()

    def _list_files(self, args: ListFilesArgs) -> str:
        start = resolve_workspace_path(self.root, args.path)
        if not start.is_dir():
            raise ToolValidationError("Path is not a directory")
        result = []
        base_depth = len(start.relative_to(self.root).parts)
        for current, directories, filenames in os.walk(start):
            current_path = Path(current)
            depth = len(current_path.relative_to(self.root).parts) - base_depth
            directories[:] = [
                item for item in directories
                if item not in IGNORED_DIRECTORIES
                and not _sensitive(current_path / item)
            ]
            if depth > args.max_depth:
                directories.clear()
                continue
            for name in [*directories, *filenames]:
                item = current_path / name
                if _sensitive(item):
                    continue
                result.append(str(item.relative_to(self.root)))
                if len(result) >= 500:
                    result.append("[Listing truncated at 500 entries]")
                    return "\n".join(result)
        return "\n".join(result) or "(No visible files found)"

    def _search(self, args: SearchArgs) -> str:
        start = resolve_workspace_path(self.root, args.path)
        if not start.is_dir():
            raise ToolValidationError("Search path is not a directory")
        matches = []
        query = args.query.casefold()
        for current, directories, filenames in os.walk(start):
            current_path = Path(current)
            directories[:] = [
                item for item in directories
                if item not in IGNORED_DIRECTORIES
                and not _sensitive(current_path / item)
            ]
            for filename in filenames:
                candidate = current_path / filename
                if _sensitive(candidate):
                    continue
                relative = str(candidate.relative_to(self.root))
                if query in filename.casefold():
                    matches.append(f"{relative}: [filename match]")
                if args.search_content:
                    try:
                        safe_candidate = resolve_workspace_path(
                            self.root, relative, allow_root=False
                        )
                        if safe_candidate != candidate or _sensitive(safe_candidate):
                            continue
                        if safe_candidate.stat().st_size > MAX_FILE_BYTES:
                            continue
                        with safe_candidate.open("rb") as stream:
                            raw_content = stream.read(MAX_FILE_BYTES + 1)
                        if len(raw_content) > MAX_FILE_BYTES:
                            continue
                        content = raw_content.decode("utf-8")
                    except (OSError, ToolValidationError, UnicodeDecodeError):
                        continue
                    if query in content.casefold():
                        line_number = next(
                            index for index, line in enumerate(content.splitlines(), 1)
                            if query in line.casefold()
                        )
                        snippet = _redact(content.splitlines()[line_number - 1].strip())
                        matches.append(f"{relative}:{line_number}: {snippet[:300]}")
                if len(matches) >= args.max_results:
                    return "\n".join(matches)
        return "\n".join(matches) or "(No matches found)"

    def _read_file(self, args: ReadFileArgs) -> str:
        path = resolve_workspace_path(self.root, args.path, allow_root=False)
        if _sensitive(path):
            raise ToolValidationError("Reading sensitive files is not allowed")
        if not path.is_file():
            raise ToolValidationError("File does not exist")
        try:
            with path.open("rb") as stream:
                content = stream.read(MAX_FILE_BYTES + 1)
            if len(content) > MAX_FILE_BYTES:
                raise ToolValidationError("File exceeds the 1 MB read limit")
            return _bounded(_redact(content.decode("utf-8")))
        except UnicodeDecodeError as exc:
            raise ToolValidationError("File is not valid UTF-8 text") from exc
        except OSError as exc:
            raise ToolValidationError("Could not read the requested file") from exc

    def _write_file(
        self,
        args: WriteFileArgs,
        policy: ActionPolicy,
    ) -> ApprovalRequired:
        path = resolve_workspace_path(self.root, args.path, allow_root=False)
        if _sensitive(path):
            raise ToolValidationError("Writing sensitive files is not allowed")
        if not path.parent.is_dir():
            raise ToolValidationError("Parent directory does not exist")
        if path.exists() and not path.is_file():
            raise ToolValidationError("Target is not a regular file")
        if path.is_symlink():
            raise ToolValidationError("Writing through symbolic links is not allowed")
        _validate_generated_content(path, args.content)
        try:
            if path.exists():
                with path.open("rb") as stream:
                    old_bytes = stream.read(MAX_FILE_BYTES + 1)
            else:
                old_bytes = None
            if old_bytes is not None and len(old_bytes) > MAX_FILE_BYTES:
                raise ToolValidationError("Existing file exceeds the 1 MB edit limit")
            old = old_bytes.decode("utf-8") if old_bytes is not None else ""
        except ToolValidationError:
            raise
        except (OSError, UnicodeDecodeError) as exc:
            raise ToolValidationError("Existing file cannot be safely edited as UTF-8") from exc
        normalized_old = old.replace("\r\n", "\n")
        normalized_new = args.content.replace("\r\n", "\n")
        if old_bytes is not None and normalized_old == normalized_new:
            raise ToolValidationError("The requested file content is unchanged")
        diff = "".join(difflib.unified_diff(
            old.splitlines(keepends=True),
            args.content.splitlines(keepends=True),
            fromfile=f"a/{path.relative_to(self.root)}",
            tofile=f"b/{path.relative_to(self.root)}",
        ))
        if not diff:
            raise ToolValidationError("The requested file content is unchanged")
        if len(diff) > MAX_TOOL_OUTPUT:
            raise ToolValidationError(
                "The full edit diff is too large to preview safely; split this edit into smaller changes."
            )
        detail = f"Write {path.relative_to(self.root)}"
        raise ApprovalRequired(
            "write_file",
            detail,
            diff,
            {
                **args.model_dump(),
                "path": str(path.relative_to(self.root)),
                "expected_sha256": (
                    hashlib.sha256(old_bytes).hexdigest()
                    if old_bytes is not None
                    else None
                ),
            },
            policy,
        )

    async def apply_write(
        self,
        relative: str,
        content: str,
        expected_sha256: str | None,
    ) -> str:
        path = resolve_workspace_path(self.root, relative, allow_root=False)
        if _sensitive(path) or not path.parent.is_dir():
            raise ToolValidationError("Write target is not permitted")
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise ToolValidationError("Write target is not a regular file")
        if len(content.encode("utf-8")) > MAX_FILE_BYTES:
            raise ToolValidationError("Write content exceeds the 1 MB limit")
        try:
            if path.exists():
                with path.open("rb") as stream:
                    current = stream.read(MAX_FILE_BYTES + 1)
            else:
                current = None
        except OSError as exc:
            raise ToolValidationError("Could not verify the approved file state") from exc
        if current is not None and len(current) > MAX_FILE_BYTES:
            raise ToolValidationError("File changed after approval or exceeds the 1 MB edit limit.")
        current_sha256 = hashlib.sha256(current).hexdigest() if current is not None else None
        if current_sha256 != expected_sha256:
            raise ToolValidationError(
                "File changed after approval was requested; review the new diff before writing."
            )
        await asyncio.to_thread(path.write_text, content, encoding="utf-8")
        return f"Applied write to {path.relative_to(self.root)}"

    async def _git(self, *arguments: str) -> str:
        git = shutil.which("git")
        if git is None:
            raise ToolValidationError("Git is not installed or not on PATH")
        returncode, output = await _run_process(
            [git, "-C", str(self.root), *arguments],
            self.root,
        )
        if returncode:
            raise ToolValidationError(output or "Git operation failed")
        return output

    async def run_approved_command(self, command: str) -> str:
        if command not in get_args(RunCommandArgs.model_fields["command"].annotation):
            raise ToolValidationError("Command is not allowlisted")
        argv = command.split()
        executable, *arguments = argv
        if os.name == "nt" and executable == "npm":
            runner = os.environ.get("COMSPEC", "cmd.exe")
            process_arguments = [runner, "/d", "/s", "/c", command]
        else:
            resolved_executable = shutil.which(executable)
            if resolved_executable is None:
                raise ToolValidationError(f"Required command is unavailable: {executable}")
            process_arguments = [resolved_executable, *arguments]
        returncode, output = await _run_process(process_arguments, self.root)
        return f"Exit code: {returncode}\n{output}"

    async def create_approved_commit(self, paths: list[str], message: str) -> str:
        resolved_paths = [
            str(resolve_workspace_path(self.root, item, allow_root=False).relative_to(self.root))
            for item in paths
        ]
        if not message.strip() or "\n" in message or "\r" in message:
            raise ToolValidationError("Commit message must be a single non-empty line")
        if any(_sensitive(self.root / item) for item in resolved_paths):
            raise ToolValidationError("Committing sensitive files is not allowed")
        await self._run_git_command("add", "--", *resolved_paths)
        return await self._run_git_command("commit", "-m", message)

    async def _run_git_command(self, *arguments: str) -> str:
        git = shutil.which("git")
        if git is None:
            raise ToolValidationError("Git is not installed or not on PATH")
        returncode, result = await _run_process(
            [git, "-C", str(self.root), *arguments],
            self.root,
        )
        if returncode:
            raise ToolValidationError(result or "Git command failed")
        return result
