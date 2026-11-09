import asyncio
import os
import socket
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

import httpx

from workspace_tools import MAX_TOOL_OUTPUT, _redact


STARTUP_TIMEOUT_SECONDS = 15
SERVER_STOP_TIMEOUT_SECONDS = 5


@dataclass
class LocalServer:
    id: str
    workspace: Path
    process: subprocess.Popen[bytes]
    output: bytearray
    reader: threading.Thread
    url: str
    health_path: str
    started_at: float


SERVERS: dict[str, LocalServer] = {}


def _read_output(server_process, output: bytearray) -> None:
    if server_process.stdout is None:
        return
    try:
        while chunk := server_process.stdout.read(4096):
            output.extend(chunk[: max(0, MAX_TOOL_OUTPUT - len(output))])
    except (OSError, ValueError):
        return


def _available_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def _server_error(output: bytearray, process: subprocess.Popen[bytes]) -> str:
    details = _redact(output.decode("utf-8", errors="replace")).strip()
    if details:
        return details[-2000:]
    returncode = process.poll()
    if returncode is None:
        return (
            "Server process remained running, but its health endpoint did not "
            "return HTTP 200."
        )
    return f"Server process exited with code {returncode} before health verification."


async def start_local_server(
    workspace: Path,
    script: str,
    health_path: str,
) -> tuple[str, str]:
    path = workspace / script
    port = _available_port()
    environment = os.environ.copy()
    environment.update({
        "NEXUS_HOST": "127.0.0.1",
        "NEXUS_PORT": str(port),
    })
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    try:
        process = subprocess.Popen(
            [sys.executable, str(path)],
            cwd=workspace,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            shell=False,
            creationflags=flags,
            start_new_session=(os.name != "nt"),
        )
    except OSError as exc:
        raise RuntimeError(
            f"Could not start the approved local app: {exc.strerror or 'process creation failed'}"
        ) from exc

    output = bytearray()
    reader = threading.Thread(
        target=_read_output,
        args=(process, output),
        daemon=True,
    )
    reader.start()
    url = f"http://127.0.0.1:{port}"
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(connect=0.5, read=1.0, write=1.0, pool=1.0),
            trust_env=False,
        ) as client:
            deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError(_server_error(output, process))
                try:
                    response = await client.get(f"{url}{health_path}")
                    if response.status_code == 200:
                        server_id = str(uuid.uuid4())
                        SERVERS[server_id] = LocalServer(
                            id=server_id,
                            workspace=workspace,
                            process=process,
                            output=output,
                            reader=reader,
                            url=url,
                            health_path=health_path,
                            started_at=time.time(),
                        )
                        return server_id, url
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(0.2)
        raise RuntimeError(
            f"Local health check failed for {url}{health_path} "
            f"within {STARTUP_TIMEOUT_SECONDS} seconds. {_server_error(output, process)}"
        )
    except BaseException:
        if process.poll() is None:
            process.terminate()
            try:
                await asyncio.wait_for(
                    asyncio.to_thread(process.wait),
                    timeout=SERVER_STOP_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                process.kill()
                await asyncio.to_thread(process.wait)
        if process.stdout is not None:
            process.stdout.close()
        await asyncio.to_thread(reader.join)
        raise


async def stop_local_server(server_id: str) -> bool:
    server = SERVERS.pop(server_id, None)
    if server is None:
        return False
    if server.process.poll() is None:
        server.process.terminate()
        try:
            await asyncio.wait_for(
                asyncio.to_thread(server.process.wait),
                timeout=SERVER_STOP_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            server.process.kill()
            await asyncio.to_thread(server.process.wait)
    if server.process.stdout is not None:
        server.process.stdout.close()
    await asyncio.to_thread(server.reader.join)
    return True


async def stop_all_local_servers() -> None:
    for server_id in list(SERVERS):
        await stop_local_server(server_id)


def list_local_servers(workspace: Path | None = None) -> list[dict]:
    return [
        {
            "id": server.id,
            "url": server.url,
            "health_path": server.health_path,
            "workspace": str(server.workspace),
            "running": server.process.poll() is None,
        }
        for server in SERVERS.values()
        if workspace is None or server.workspace == workspace
    ]
