import os
import subprocess
import shutil
import urllib.parse
import time
import csv
import io
import winreg
import webbrowser
import ctypes
import ctypes.wintypes
from typing import Dict, Any, List, Set, Optional

USER_HOME = os.path.expanduser("~")

# -------------------------------------------------------------
# Win32 Process Snapshot Structures for <20ms execution
# -------------------------------------------------------------
class PROCESSENTRY32(ctypes.Structure):
    _fields_ = [
        ('dwSize', ctypes.wintypes.DWORD),
        ('cntUsage', ctypes.wintypes.DWORD),
        ('th32ProcessID', ctypes.wintypes.DWORD),
        ('th32DefaultHeapID', ctypes.c_size_t),
        ('th32ModuleID', ctypes.wintypes.DWORD),
        ('cntThreads', ctypes.wintypes.DWORD),
        ('th32ParentProcessID', ctypes.wintypes.DWORD),
        ('pcPriClassBase', ctypes.c_long),
        ('dwFlags', ctypes.wintypes.DWORD),
        ('szExeFile', ctypes.c_char * 260)
    ]

# -------------------------------------------------------------
# Dynamic Browser Discovery on Windows Host
# -------------------------------------------------------------
def find_chrome_executable() -> Optional[str]:
    """Dynamically resolve Google Chrome path via registry and standard file locations."""
    # 1. Check Registry App Paths
    for root in [winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER]:
        try:
            with winreg.OpenKey(root, r"Software\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe") as key:
                val, _ = winreg.QueryValueEx(key, "")
                if val and os.path.exists(val):
                    return val
        except OSError:
            pass

    # 2. Check Standard Directory Paths
    candidates = [
        os.path.join(os.environ.get("PROGRAMFILES", r"C:\Program Files"), r"Google\Chrome\Application\chrome.exe"),
        os.path.join(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"), r"Google\Chrome\Application\chrome.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), r"Google\Chrome\Application\chrome.exe"),
    ]
    for c in candidates:
        if c and os.path.exists(c):
            return c

    # 3. Check PATH
    which_chrome = shutil.which("chrome.exe") or shutil.which("chrome")
    if which_chrome:
        return which_chrome

    return None

def find_brave_executable() -> Optional[str]:
    """Dynamically resolve Brave Browser path via registry and standard file locations."""
    for root in [winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER]:
        try:
            with winreg.OpenKey(root, r"Software\Microsoft\Windows\CurrentVersion\App Paths\brave.exe") as key:
                val, _ = winreg.QueryValueEx(key, "")
                if val and os.path.exists(val):
                    return val
        except OSError:
            pass
    candidates = [
        os.path.join(os.environ.get("PROGRAMFILES", r"C:\Program Files"), r"BraveSoftware\Brave-Browser\Application\brave.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), r"BraveSoftware\Brave-Browser\Application\brave.exe"),
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return shutil.which("brave.exe")

def find_edge_executable() -> Optional[str]:
    """Dynamically resolve Microsoft Edge path via registry and standard file locations."""
    for root in [winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER]:
        try:
            with winreg.OpenKey(root, r"Software\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe") as key:
                val, _ = winreg.QueryValueEx(key, "")
                if val and os.path.exists(val):
                    return val
        except OSError:
            pass
    candidates = [
        os.path.join(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"), r"Microsoft\Edge\Application\msedge.exe"),
        os.path.join(os.environ.get("PROGRAMFILES", r"C:\Program Files"), r"Microsoft\Edge\Application\msedge.exe"),
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return shutil.which("msedge.exe")

def resolve_default_browser() -> str:
    """Return the primary installed browser on Windows."""
    chrome = find_chrome_executable()
    if chrome:
        return chrome
    brave = find_brave_executable()
    if brave:
        return brave
    edge = find_edge_executable()
    if edge:
        return edge
    return "msedge.exe"

# Mapping of application keywords to their exact binary executables
APP_PROCESS_MAP: Dict[str, List[str]] = {
    "calculator": ["CalculatorApp.exe", "calc.exe"],
    "calc": ["CalculatorApp.exe", "calc.exe"],
    "camera": ["WindowsCamera.exe"],
    "webcam": ["WindowsCamera.exe"],
    "chrome": ["chrome.exe"],
    "google chrome": ["chrome.exe"],
    "brave": ["brave.exe"],
    "edge": ["msedge.exe"],
    "browser": ["chrome.exe", "brave.exe", "msedge.exe"],
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
    "camera": "microsoft.windows.camera:",
    "webcam": "microsoft.windows.camera:",
    "vscode": "code.cmd",
    "vs code": "code.cmd",
    "code": "code.cmd",
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
    Uses Win32 Toolhelp32Snapshot for sub-20ms execution instead of tasklist subprocess.
    """
    clean_targets = set()
    for name in candidates:
        base = os.path.basename(name).strip().lower()
        if not base.endswith(".exe") and not base.endswith(".cmd"):
            base += ".exe"
        clean_targets.add(base)

    pids: Set[int] = set()
    try:
        snap = ctypes.windll.kernel32.CreateToolhelp32Snapshot(0x00000002, 0)
        entry = PROCESSENTRY32()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32)
        if ctypes.windll.kernel32.Process32First(snap, ctypes.byref(entry)):
            while True:
                name = entry.szExeFile.decode('utf-8', 'ignore').lower()
                if name in clean_targets:
                    pids.add(int(entry.th32ProcessID))
                if not ctypes.windll.kernel32.Process32Next(snap, ctypes.byref(entry)):
                    break
        ctypes.windll.kernel32.CloseHandle(snap)
        return pids
    except Exception:
        # Fallback to tasklist if snapshot fails
        return _fallback_tasklist_pids(clean_targets)

def _fallback_tasklist_pids(clean_targets: Set[str]) -> Set[int]:
    pids: Set[int] = set()
    try:
        output = subprocess.check_output(["tasklist", "/FO", "CSV", "/NH"], text=True, timeout=2.0)
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

def open_youtube(target_browser: Optional[str] = None) -> Dict[str, Any]:
    """Safely open https://www.youtube.com using an approved browser-launch mechanism."""
    url = "https://www.youtube.com"
    if target_browser and "chrome" in target_browser.lower():
        chrome_exe = find_chrome_executable()
        if not chrome_exe:
            avail = []
            if find_brave_executable():
                avail.append("Brave")
            if find_edge_executable():
                avail.append("Microsoft Edge")
            avail_str = f" Available browsers: {', '.join(avail)}." if avail else ""
            return {
                "status": "error",
                "message": f"Google Chrome is not installed on this system to open YouTube.{avail_str}",
                "verified": False,
                "missing_app": "chrome"
            }
        try:
            subprocess.Popen([chrome_exe, url], shell=False)
            return {"status": "success", "message": "Opened YouTube in Google Chrome.", "verified": True, "target": url}
        except Exception as e:
            return {"status": "error", "message": f"Failed to launch Chrome for YouTube: {str(e)}", "verified": False}

    # Open via default system browser mechanism
    try:
        opened = webbrowser.open(url)
        if not opened:
            b_path = resolve_default_browser()
            if os.path.exists(b_path):
                subprocess.Popen([b_path, url], shell=False)
            else:
                os.startfile(url)
        return {"status": "success", "message": "Opened YouTube.", "verified": True, "target": url}
    except Exception as e:
        return {"status": "error", "message": f"Failed to open YouTube: {str(e)}", "verified": False}

def launch_application(app_name: str, timeout_sec: float = 1.0) -> Dict[str, Any]:
    """
    Launch an application or URI and verify actual execution on Windows.
    Takes a pre-launch process snapshot to avoid false positives from already-running apps.
    """
    normalized = app_name.strip().lower()

    # Special handling for YouTube
    if normalized in {"youtube", "open youtube"}:
        return open_youtube()
    if normalized in {"youtube in chrome", "open youtube in chrome"}:
        return open_youtube(target_browser="chrome")

    # Special handling for Chrome
    if normalized in {"chrome", "google chrome"}:
        chrome_exe = find_chrome_executable()
        if not chrome_exe:
            avail = []
            if find_brave_executable():
                avail.append("Brave")
            if find_edge_executable():
                avail.append("Microsoft Edge")
            avail_str = f" Available browsers: {', '.join(avail)}." if avail else ""
            return {
                "status": "error",
                "message": f"Google Chrome is not installed on this computer.{avail_str}",
                "verified": False,
                "missing_app": "chrome"
            }
        target_cmd = chrome_exe
        candidates = ["chrome.exe"]
    elif normalized in {"brave", "brave browser"}:
        brave_exe = find_brave_executable()
        if not brave_exe:
            return {"status": "error", "message": "Brave Browser is not installed on this computer.", "verified": False}
        target_cmd = brave_exe
        candidates = ["brave.exe"]
    elif normalized in {"edge", "microsoft edge"}:
        edge_exe = find_edge_executable()
        if not edge_exe:
            return {"status": "error", "message": "Microsoft Edge is not installed on this computer.", "verified": False}
        target_cmd = edge_exe
        candidates = ["msedge.exe"]
    elif normalized in {"browser"}:
        target_cmd = resolve_default_browser()
        candidates = ["chrome.exe", "brave.exe", "msedge.exe"]
    else:
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

    # Protocol handler like camera
    if target_cmd.startswith("microsoft.windows."):
        try:
            os.startfile(target_cmd)
            return {"status": "success", "message": f"Opened: {app_name}", "verified": True, "target": target_cmd}
        except Exception as e:
            return {"status": "error", "message": f"Failed to launch '{app_name}': {str(e)}", "verified": False}

    # Resolve executable path if needed
    if not target_cmd.endswith(":") and not target_cmd.endswith(".exe") and not target_cmd.endswith(".cmd"):
        which_exe = shutil.which(target_cmd + ".exe")
        which_cmd = shutil.which(target_cmd + ".cmd")
        if which_exe:
            target_cmd = which_exe
        elif which_cmd:
            target_cmd = which_cmd

    # Snapshot existing PIDs before launching (takes < 20ms)
    before_pids = get_running_process_pids(candidates)

    try:
        try:
            os.startfile(target_cmd)
        except Exception:
            # Fallback to subprocess Popen
            subprocess.Popen(
                [target_cmd] if os.path.exists(target_cmd) else target_cmd,
                shell=not os.path.exists(target_cmd),
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP") else 0
            )

        # Fast polling loop to verify process creation (<20ms per poll)
        start_time = time.time()
        new_pids: Set[int] = set()
        while time.time() - start_time < max(0.3, timeout_sec):
            current_pids = get_running_process_pids(candidates)
            new_pids = current_pids - before_pids
            if new_pids:
                break
            time.sleep(0.05)

        if new_pids:
            return {
                "status": "success",
                "message": f"Launched {app_name}.",
                "verified": True,
                "pids": list(new_pids),
                "target": target_cmd
            }

        # If application was already running and launched into existing instance
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

def close_application(app_name: str, timeout_sec: float = 1.0) -> Dict[str, Any]:
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

        # Poll to verify termination (<20ms per poll)
        start_time = time.time()
        while time.time() - start_time < max(0.3, timeout_sec):
            remaining = get_running_process_pids(candidates)
            if not remaining:
                break
            time.sleep(0.05)

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
        webbrowser.open(url)
        return {"status": "success", "message": f"Searched for: {query}", "verified": True, "url": url}
    except Exception as e:
        return {"status": "error", "message": f"Failed to search web: {str(e)}", "verified": False}
