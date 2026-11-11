import os
import subprocess
import shutil
import urllib.parse
from typing import Dict, Any, Optional

USER_HOME = os.path.expanduser("~")

def is_process_running(proc_name: str) -> bool:
    """Verify whether a process is actively running on Windows using tasklist."""
    try:
        clean = os.path.basename(proc_name).strip().lower()
        if not clean.endswith(".exe") and not clean.endswith(".cmd"):
            clean += ".exe"
        output = subprocess.check_output(
            ["tasklist", "/NH", "/FI", f"IMAGENAME eq {clean}"],
            text=True,
            timeout=2.0
        )
        return clean in output.lower()
    except Exception:
        return False

KNOWN_APPS: Dict[str, str] = {
    "notepad": "notepad.exe",
    "calculator": "calc.exe",
    "calc": "calc.exe",
    "chrome": "chrome.exe",
    "google chrome": "chrome.exe",
    "browser": "chrome.exe",
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

def launch_application(app_name: str) -> Dict[str, Any]:
    """Launch an application, URI, or system folder."""
    normalized = app_name.strip().lower()
    
    target_cmd = KNOWN_APPS.get(normalized, normalized)
    
    try:
        # Check if it's a protocol (like camera or spotify) or URL or directory
        if "://" in target_cmd or target_cmd.endswith(":") or os.path.isdir(target_cmd) or os.path.isfile(target_cmd):
            os.startfile(target_cmd)
            return {"status": "success", "message": f"Opened: {app_name}"}
            
        if not target_cmd.endswith(".exe") and not target_cmd.endswith(".cmd"):
            if shutil.which(target_cmd + ".exe"):
                target_cmd = target_cmd + ".exe"
            elif shutil.which(target_cmd + ".cmd"):
                target_cmd = target_cmd + ".cmd"
                
        # Try os.startfile first for clean native Windows launch
        try:
            os.startfile(target_cmd)
            # Short verification window for executables
            verified = True
            if target_cmd.endswith(".exe"):
                import time
                time.sleep(0.12)
                verified = is_process_running(target_cmd)
            return {"status": "success", "message": f"Launched {app_name}.", "verified": verified, "target": target_cmd}
        except Exception:
            # Fallback to subprocess Popen detached
            proc = subprocess.Popen(
                target_cmd,
                shell=True,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP") else 0
            )
            import time
            time.sleep(0.12)
            verified = proc.poll() is None
            return {"status": "success", "message": f"Started {app_name} with PID {proc.pid}", "pid": proc.pid, "verified": verified}
    except Exception as e:
        return {"status": "error", "message": f"Failed to launch '{app_name}': {str(e)}", "verified": False}

def close_application(app_name: str) -> Dict[str, Any]:
    """Close an application by process name with verified termination check."""
    normalized = app_name.strip().lower()
    proc_name = KNOWN_APPS.get(normalized, normalized)
    if not proc_name.endswith(".exe"):
        proc_name += ".exe"
        
    try:
        res = subprocess.run(
            ["taskkill", "/IM", proc_name, "/F"],
            capture_output=True,
            text=True
        )
        import time
        time.sleep(0.1)
        still_running = is_process_running(proc_name)
        if not still_running:
            return {"status": "success", "message": f"Successfully terminated {app_name}.", "verified": True}
        else:
            return {"status": "warning", "message": f"Process {app_name} was not running or could not be killed.", "verified": False}
    except Exception as e:
        return {"status": "error", "message": f"Failed to close '{app_name}': {str(e)}", "verified": False}

def open_path(path: str) -> Dict[str, Any]:
    """Open a file or directory in Windows Explorer or default app."""
    try:
        expanded = os.path.expanduser(os.path.expandvars(path))
        if not os.path.exists(expanded):
            return {"status": "error", "message": f"Path does not exist: {path}"}
        os.startfile(expanded)
        return {"status": "success", "message": f"Opened: {expanded}"}
    except Exception as e:
        return {"status": "error", "message": f"Failed to open '{path}': {str(e)}"}

def search_web_in_browser(query: str) -> Dict[str, Any]:
    """Perform a web search in the user's default browser."""
    try:
        encoded = urllib.parse.quote_plus(query)
        url = f"https://www.google.com/search?q={encoded}"
        os.startfile(url)
        return {"status": "success", "message": f"Searching web for '{query}' in browser."}
    except Exception as e:
        return {"status": "error", "message": f"Failed to search web: {str(e)}"}
