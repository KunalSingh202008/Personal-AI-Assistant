"""
KELA PC Control Engine
Provides native Windows desktop automation, app management, volume,
system diagnostics, file searching, and screen capture.
"""

from .app_launcher import launch_application, close_application, open_path, search_web_in_browser
from .volume_control import set_volume, change_volume, toggle_mute
from .system_ops import get_system_metrics, list_running_processes
from .screenshot import capture_desktop_screenshot
from .file_search import (
    search_user_files,
    find_resume_files,
    find_latest_file,
    create_user_folder,
    open_file_path,
)

__all__ = [
    "launch_application",
    "close_application",
    "open_path",
    "search_web_in_browser",
    "set_volume",
    "change_volume",
    "toggle_mute",
    "get_system_metrics",
    "list_running_processes",
    "capture_desktop_screenshot",
    "search_user_files",
    "find_resume_files",
    "find_latest_file",
    "create_user_folder",
    "open_file_path",
]
