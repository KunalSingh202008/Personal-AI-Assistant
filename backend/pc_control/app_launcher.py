import os
import subprocess
import shutil
import urllib.parse
import time
import csv
import io
from typing import Dict, Any, List, Set, Optional

USER_HOME = os.path.expanduser("~")

BRAVE_PATH = r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"
EDGE_PATH = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

def resolve_default_browser() -> str:
    """Detect available Chromium browser on Windows host."""
    for path in [CHROME_PATH, BRAVE_PATH, EDGE_PATH]:
        if os.path.exists(path):
            return path
    if shutil.which("chrome.exe"):
        return "chrome.exe"
    if shutil.which("brave.exe"):
        return "brave.exe"
    if shutil.which("msedge.exe"):
        return "msedge.exe"
    return "https://www.google.com"

ACTIVE_BROWSER = resolve_default_browser()

# Mapping of application keywords to their exact binary executables
APP_PROCESS_MAP: Dict[str, List[str]] = {
    "calculator": ["CalculatorApp.exe", "calc.exe"],
    "calc": ["CalculatorApp.exe", "calc.exe"],
    "camera": ["WindowsCamera.exe"],
    "webcam": ["WindowsCamera.exe"],
    "chrome": ["chrome.exe", "brave.exe", "msedge.exe"],
    "google chrome": ["chrome.exe", "brave.exe", "msedge.exe"],
    "browser": ["brave.exe", "chrome.exe", "msedge.exe"],
    "brave": ["brave.exe"],
    "edge": ["msedge.exe"],
    "vscode": ["Code.exe"],
    "vs code": ["Code.exe"],
    "code": ["Code.exe"],
    "notepad": ["Notepad.exe"],
    "spotify": ["Spotify.exe"],
    "terminal": ["WindowsTerminal.exe", "wt.exe"],
    "cmd": ["cmd.exe"],
    "powershell": ["powershell.exe"],
    "task manager": ["Taskmgr.exe"],
    "taskmgr": ["Taskmgr.exe"],
    "paint": ["mspaint.exe", "PaintApp.exe"],
    "mspaint": ["mspaint.exe", "PaintApp.exe"],
    "explorer": ["explorer.exe"],
    "file explorer": ["explorer.exe"],
    "files": ["explorer.exe"],
}

KNOWN_APPS: Dict[str, str] = {
    "notepad": "notepad.exe",
    "calculator": "calc.exe",
    "calc": "calc.exe",
    "chrome": ACTIVE_BROWSER,
    "google chrome": ACTIVE_BROWSER,
    "browser": ACTIVE_BROWSER,
    "brave": BRAVE_PATH,
    "edge": EDGE_PATH,
    "vscode": "code.cmd",
    "vs code": "code.cmd",
    "code": "code.cmd",
    "camera": "microsoft.windows.camera:",
    "webcam": "microsoft.windows.camera:",
    "terminal": "wt.exe",
    "cmd": "cmd.exe",
    "powershell": "powershell.exe",
    "task manager": "taskmgr.exe",
    "taskmgr": "taskmgr.exe",
    "paint": "mspaint.exe",
    "mspaint": "mspaint.exe",
    "explorer": "explorer.exe",
    "file explorer": "explorer.exe",
    "files": "explorer.exe",
    "spotify": "spotify.exe",
    "youtube": "https://www.youtube.com",
    "downloads": os.path.join(USER_HOME, "Downloads"),
    "documents": os.path.join(USER_HOME, "Documents"),
    "desktop": os.path.join(USER_HOME, "Desktop"),
}

def get_running_process_pids(candidates: List[str]) -> Set[int]:
    """
    Return set of active Windows PIDs matching exact executable names.
    Parses CSV output from 'tasklist /FO CSV /NH' to avoid substring collisions.
    """
    clean_targets = set()
    for name in candidates:
        base = os.path.basename(name).strip().lower()
        if not base.endswith(".exe") and not base.endswith(".cmd"):
            base += ".exe"
        clean_targets.add(base)

    pids: Set[int] = set()
    try:
        output = subprocess.check_output(["tasklist", "/FO", "CSV", "/NH"], text=True, timeout=2.5)
        reader = csv.reader(io.StringIO(output))
        for row in reader:
            if len(row) >= 2:
                proc_img = row[0].strip().lower()
                if proc_img in clean_targets:
                    try:
                        pids.add(int(row[1].strip()))
                    except ValueError:
                        pass
    except Exception:
        pass
    return pids

def is_process_running(proc_name: str) -> bool:
    """Verify whether any process matching the application name or executable is active."""
    normalized = proc_name.strip().lower()
    candidates = APP_PROCESS_MAP.get(normalized, [proc_name])
    return len(get_running_process_pids(candidates)) > 0

def launch_application(app_name: str, timeout_sec: float = 2.5) -> Dict[str, Any]:
    """
    Launch an application or URI and verify actual execution on Windows.
    Takes a pre-launch process snapshot to avoid false positives from already-running apps.
    """
    normalized = app_name.strip().lower()
    target_cmd = KNOWN_APPS.get(normalized, normalized)
    candidates = APP_PROCESS_MAP.get(normalized, [target_cmd])

    # Check for URLs, system folders, or general file paths
    is_uri_or_path = (
        "://" in target_cmd
        or (target_cmd.endswith(":") and not target_cmd.startswith("microsoft.windows."))
        or os.path.isdir(target_cmd)
        or os.path.isfile(target_cmd)
    )

    if is_uri_or_path:
        try:
            os.startfile(target_cmd)
            return {"status": "success", "message": f"Opened: {app_name}", "verified": True, "target": target_cmd}
        except Exception as e:
            return {"status": "error", "message": f"Failed to open '{app_name}': {str(e)}", "verified": False}

    # Resolve executable path if needed
    if not target_cmd.endswith(":") and not target_cmd.endswith(".exe") and not target_cmd.endswith(".cmd"):
        which_exe = shutil.which(target_cmd + ".exe")
        which_cmd = shutil.which(target_cmd + ".cmd")
        if which_exe:
            target_cmd = which_exe
        elif which_cmd:
            target_cmd = which_cmd

    # Snapshot existing PIDs before launching
    before_pids = get_running_process_pids(candidates)

    try:
        try:
            os.startfile(target_cmd)
        except Exception:
            # Fallback to subprocess Popen detached
            subprocess.Popen(
                target_cmd,
                shell=True,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP") else 0
            )

        # Configurable polling loop to verify process creation
        start_time = time.time()
        new_pids: Set[int] = set()
        while time.time() - start_time < max(0.5, timeout_sec):
            current_pids = get_running_process_pids(candidates)
            new_pids = current_pids - before_pids
            if new_pids:
                break
            time.sleep(0.1)

        if new_pids:
            return {
                "status": "success",
                "message": f"Launched {app_name}.",
                "verified": True,
                "pids": list(new_pids),
                "target": target_cmd
            }

        # If application was already running and launched into existing instance (e.g. Chrome tab)
        current_pids = get_running_process_pids(candidates)
        if current_pids:
            return {
                "status": "success",
                "message": f"{app_name.title()} is active.",
                "verified": True,
                "already_running": True,
                "pids": list(current_pids),
                "target": target_cmd
            }

        # If neither new PID nor existing PID confirmed after timeout: actionable failure
        return {
            "status": "error",
            "message": f"Failed to verify launch for '{app_name}': process did not start within {timeout_sec}s.",
            "verified": False,
            "target": target_cmd
        }
    except Exception as e:
        return {"status": "error", "message": f"Failed to launch '{app_name}': {str(e)}", "verified": False}

def close_application(app_name: str, timeout_sec: float = 2.0) -> Dict[str, Any]:
    """
    Close an application by terminating its process tree and verifying termination.
    """
    normalized = app_name.strip().lower()
    candidates = APP_PROCESS_MAP.get(normalized, [normalized])

    initial_pids = get_running_process_pids(candidates)
    if not initial_pids:
        return {"status": "warning", "message": f"Process {app_name} was not running.", "verified": True}

    try:
        for candidate in candidates:
            clean = candidate if candidate.endswith(".exe") else f"{candidate}.exe"
            subprocess.run(["taskkill", "/IM", clean, "/F", "/T"], capture_output=True, text=True)

        # Poll to verify termination
        start_time = time.time()
        while time.time() - start_time < max(0.5, timeout_sec):
            remaining = get_running_process_pids(candidates)
            if not remaining:
                break
            time.sleep(0.1)

        remaining = get_running_process_pids(candidates)
        if not remaining:
            return {
                "status": "success",
                "message": f"Successfully terminated {app_name}.",
                "verified": True,
                "terminated_pids": list(initial_pids)
            }
        else:
            return {
                "status": "error",
                "message": f"Process {app_name} could not be completely terminated within {timeout_sec}s.",
                "verified": False,
                "remaining_pids": list(remaining)
            }
    except Exception as e:
        return {"status": "error", "message": f"Failed to close '{app_name}': {str(e)}", "verified": False}

def open_path(path: str) -> Dict[str, Any]:
    """Open a file or directory in Windows Explorer or default app."""
    try:
        expanded = os.path.expanduser(os.path.expandvars(path))
        if not os.path.exists(expanded):
            return {"status": "error", "message": f"Path does not exist: {path}", "verified": False}
        os.startfile(expanded)
        return {"status": "success", "message": f"Opened: {expanded}", "verified": True}
    except Exception as e:
        return {"status": "error", "message": f"Failed to open '{path}': {str(e)}", "verified": False}

def search_web_in_browser(query: str) -> Dict[str, Any]:
    """Perform a web search in the user's default browser."""
    try:
        encoded = urllib.parse.quote_plus(query)
        url = f"https://www.google.com/search?q={encoded}"
        os.startfile(url)
        return {"status": "success", "message": f"Searching web for '{query}' in browser.", "verified": True}
    except Exception as e:
        return {"status": "error", "message": f"Failed to search web: {str(e)}", "verified": False}
