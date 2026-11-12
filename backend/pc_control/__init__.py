"""
KELA PC Control Engine
Provides native Windows desktop automation, app management, volume,
system diagnostics, file searching, and screen capture.
"""

from .app_launcher import launch_application, close_application, open_path, search_web_in_browser
from .volume_control import set_volume, change_volume, toggle_mute
from .system_ops import get_system_metrics, list_running_processes, get_disk_space, find_large_files, open_folder
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
    "get_disk_space",
    "list_running_processes",
    "find_large_files",
    "open_folder",
    "capture_desktop_screenshot",
    "search_user_files",
    "find_resume_files",
    "find_latest_file",
    "create_user_folder",
    "open_file_path",
]
