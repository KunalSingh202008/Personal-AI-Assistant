"""
Centralized Tool Registry for KELA AI Platform.
Manages tool definitions, typed JSON schemas, risk classification (GREEN, AMBER, RED),
and execution dispatching across PC operations, system automation, and workspace tools.
"""

from typing import Dict, Any, List, Optional
import os
import action_policy
from workspace_tools import TOOL_SCHEMAS
import pc_control

# Native PC and System tool schemas with typed JSON schemas
PC_TOOL_SCHEMAS: List[Dict[str, Any]] = [
    {
        "name": "launch_app",
        "description": "Launch or focus a Windows desktop application (e.g. calculator, camera, chrome, vscode, notepad, spotify, terminal).",
        "parameters": {
            "type": "object",
            "properties": {
                "app_name": {
                    "type": "string",
                    "description": "Name or executable keyword of the application (e.g., 'calculator', 'camera', 'chrome', 'vscode', 'notepad')."
                }
            },
            "required": ["app_name"]
        }
    },
    {
        "name": "close_app",
        "description": "Close or terminate a running Windows application by name.",
        "parameters": {
            "type": "object",
            "properties": {
                "app_name": {
                    "type": "string",
                    "description": "Name or executable keyword of the application to close."
                }
            },
            "required": ["app_name"]
        }
    },
    {
        "name": "change_volume",
        "description": "Adjust system master volume up or down by step intervals.",
        "parameters": {
            "type": "object",
            "properties": {
                "direction": {
                    "type": "string",
                    "enum": ["up", "down"],
                    "description": "Direction to change volume ('up' or 'down')."
                },
                "steps": {
                    "type": "integer",
                    "description": "Number of volume steps (each step is ~2%). Default is 5.",
                    "default": 5
                }
            },
            "required": ["direction"]
        }
    },
    {
        "name": "set_volume",
        "description": "Set master system volume to a specific percentage level.",
        "parameters": {
            "type": "object",
            "properties": {
                "level": {
                    "type": "integer",
                    "description": "Volume level from 0 to 100 percent.",
                    "minimum": 0,
                    "maximum": 100
                }
            },
            "required": ["level"]
        }
    },
    {
        "name": "toggle_mute",
        "description": "Toggle master audio mute state.",
        "parameters": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "get_system_metrics",
        "description": "Retrieve real-time hardware telemetry including RAM usage percentage, memory stats, CPU load, and battery status.",
        "parameters": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "capture_desktop_screenshot",
        "description": "Capture a screenshot of the user's primary Windows desktop display.",
        "parameters": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "search_user_files",
        "description": "Search common user directories (Downloads, Documents, Desktop) for files or project folders matching a query.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query or project/file name pattern."
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of search results to return.",
                    "default": 15
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "find_resume_files",
        "description": "Locate resume, CV, or biodata documents across user directories.",
        "parameters": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "open_file_path",
        "description": "Open a specified local file in its default Windows desktop application.",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Full absolute path to the file to open."
                }
            },
            "required": ["file_path"]
        }
    },
    {
        "name": "web_search",
        "description": "Search the internet using the system browser.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query string."
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "run_project",
        "description": "Run or launch a local coding project (e.g. Phone Doctor, NexusAI). Requires user confirmation/approval.",
        "parameters": {
            "type": "object",
            "properties": {
                "project_name": {
                    "type": "string",
                    "description": "Name of the project to run."
                },
                "project_path": {
                    "type": "string",
                    "description": "Path to the project directory."
                }
            },
            "required": ["project_name"]
        }
    },
    {
        "name": "get_disk_space",
        "description": "Retrieve genuine storage metrics, total capacity, and free space across all active Windows drives.",
        "parameters": {
            "type": "object",
            "properties": {
                "drive": {
                    "type": "string",
                    "description": "Optional specific drive letter (e.g. 'C:' or 'D:')."
                }
            }
        }
    },
    {
        "name": "list_running_processes",
        "description": "Query genuine active Windows processes and top memory-consuming applications.",
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of processes to return (default: 15).",
                    "default": 15
                },
                "sort_by_memory": {
                    "type": "boolean",
                    "description": "Whether to sort by memory consumption descending.",
                    "default": True
                }
            }
        }
    },
    {
        "name": "find_large_files",
        "description": "Find large files exceeding a size threshold in user directories (Downloads, Documents, Desktop).",
        "parameters": {
            "type": "object",
            "properties": {
                "min_size_mb": {
                    "type": "integer",
                    "description": "Minimum size in megabytes (default: 100).",
                    "default": 100
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of files to return (default: 10).",
                    "default": 10
                }
            }
        }
    },
    {
        "name": "open_folder",
        "description": "Open a specified folder in Windows File Explorer.",
        "parameters": {
            "type": "object",
            "properties": {
                "folder_path": {
                    "type": "string",
                    "description": "Path or alias of folder to open (e.g., 'Downloads', 'Documents', 'Desktop', or full path)."
                }
            },
            "required": ["folder_path"]
        }
    },
    {
        "name": "launch_browser",
        "description": "Launch a specific detected browser (Edge, Brave, Chrome, Firefox) or open a URL in a browser.",
        "parameters": {
            "type": "object",
            "properties": {
                "browser_name": {
                    "type": "string",
                    "description": "Optional name of browser ('brave', 'edge', 'chrome', 'firefox')."
                },
                "url": {
                    "type": "string",
                    "description": "Optional website URL to open."
                }
            }
        }
    },
    {
        "name": "open_youtube",
        "description": "Open YouTube in a specified browser or system default browser.",
        "parameters": {
            "type": "object",
            "properties": {
                "browser_name": {
                    "type": "string",
                    "description": "Optional name of browser ('brave', 'edge', 'chrome', 'firefox')."
                }
            }
        }
    },
    {
        "name": "search_web_in_browser",
        "description": "Perform a web search for a query string in the browser (Google, YouTube, GitHub, etc.).",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query string."
                },
                "browser_name": {
                    "type": "string",
                    "description": "Optional name of browser to use."
                },
                "engine": {
                    "type": "string",
                    "description": "Optional search engine ('google', 'youtube', 'github')."
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "get_installed_applications",
        "description": "List genuine applications installed on this Windows PC via registry.",
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of applications to return (default: 50).",
                    "default": 50
                },
                "filter_term": {
                    "type": "string",
                    "description": "Optional filter substring for application name."
                }
            }
        }
    },
    {
        "name": "get_startup_applications",
        "description": "List programs configured to launch on Windows startup.",
        "parameters": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "find_duplicate_files",
        "description": "Scan user storage folders for duplicate files using safe progressive hashing.",
        "parameters": {
            "type": "object",
            "properties": {
                "directory": {
                    "type": "string",
                    "description": "Optional directory to scan (defaults to user Downloads, Documents, Desktop)."
                },
                "min_size_kb": {
                    "type": "integer",
                    "description": "Minimum file size in KB to consider (default: 50).",
                    "default": 50
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum duplicate groups to report (default: 15).",
                    "default": 15
                }
            }
        }
    },
    {
        "name": "identify_temporary_files",
        "description": "Identify temporary files and caches in %TEMP% and user directories.",
        "parameters": {
            "type": "object",
            "properties": {
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of items to return (default: 30).",
                    "default": 30
                }
            }
        }
    },
    {
        "name": "analyze_storage_cleanup",
        "description": "Comprehensive storage analysis categorizing safe cleanup candidates vs review-recommended items.",
        "parameters": {
            "type": "object",
            "properties": {
                "target_drive": {
                    "type": "string",
                    "description": "Optional target drive or path."
                }
            }
        }
    },
    {
        "name": "analyze_project_folder",
        "description": "Deeply inspect a software project folder: tech stack, git status, file count, size, and health.",
        "parameters": {
            "type": "object",
            "properties": {
                "project_path_or_name": {
                    "type": "string",
                    "description": "Name or full filesystem path of the project."
                }
            },
            "required": ["project_path_or_name"]
        }
    },
    {
        "name": "plan_system_diagnosis",
        "description": "Multi-step diagnostic audit analyzing CPU, RAM, disk bottlenecks, heavy processes, and startup apps.",
        "parameters": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "recycle_file_safely",
        "description": "Move a file to Windows Recycle Bin. Destructive action requiring user approval.",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Full path of file to recycle."
                }
            },
            "required": ["file_path"]
        }
    }
]

SAFE_VOICE_ACTIONS = {
    # System & Audio
    "volume_up", "volume_down", "set_volume", "toggle_mute", "change_volume",
    # Native Apps & Tools
    "launch_camera", "launch_youtube", "open_youtube", "launch_chrome", "launch_vscode",
    "launch_calculator", "launch_notepad", "launch_app", "close_app",
    "launch_browser", "search_web_in_browser", "get_installed_applications", "get_startup_applications",
    # File & Status
    "find_resume", "find_resume_files", "open_latest_pdf", "open_downloads",
    "screenshot", "capture_desktop_screenshot", "battery_status", "system_status",
    "get_system_metrics", "get_disk_space", "list_running_processes", "find_large_files",
    "open_folder", "time", "date",
    "web_search", "web_search_summary", "search_user_files", "open_file_path",
    # Storage & Intelligence
    "find_duplicate_files", "identify_temporary_files", "analyze_storage_cleanup",
    "analyze_project_folder", "plan_system_diagnosis",
    # Conversational / Assistant State
    "stop_listening", "pause_listening", "assistant_identity",
    "help", "identity", "projects_info", "greeting", "conversational_ai"
}

RISKY_APPROVAL_ACTIONS = {
    "run_project", "run_command", "write_file", "git_commit", "start_local_server"
}

BLOCKED_ACTIONS = {
    "format_drive", "delete_root", "destroy_system", "kill_system"
}


class ToolRegistry:
    """
    Centralized tool registry managing tool schemas, action risk levels,
    and execution boundaries across the KELA AI platform.
    """

    def __init__(self):
        # Register both workspace coding tools and native PC/system tools
        self._schemas: Dict[str, Dict[str, Any]] = {}
        for schema in TOOL_SCHEMAS:
            self._schemas[schema["name"]] = schema
        for schema in PC_TOOL_SCHEMAS:
            self._schemas[schema["name"]] = schema

    def list_schemas(self) -> List[Dict[str, Any]]:
        """Return registered JSON schemas for all available tools."""
        return list(self._schemas.values())

    def get_schema(self, tool_name: str) -> Optional[Dict[str, Any]]:
        """Retrieve schema for specific tool by name."""
        return self._schemas.get(tool_name)

    def is_safe_voice_action(self, action_name: str) -> bool:
        """Check whether action is allowlisted for safe auto-execution in voice mode."""
        return action_name in SAFE_VOICE_ACTIONS

    def get_tool_risk(self, action_name: str, arguments: Optional[Dict[str, Any]] = None) -> str:
        """
        Evaluate tool risk category (GREEN, AMBER, RED) using centralized action policy:
        - GREEN: Safe read-only inspection or allowlisted voice/PC action (auto-approved)
        - AMBER: Operations requiring explicit user confirmation / approval
        - RED: Destructive / unauthorized operations (strictly blocked)
        """
        if action_name in BLOCKED_ACTIONS:
            return "RED"
        if action_name in {"recycle_file_safely", "delete_file", "destroy_file"}:
            return "RED"
        if action_name in RISKY_APPROVAL_ACTIONS:
            return "AMBER"
        if action_name in SAFE_VOICE_ACTIONS or action_name in self._schemas:
            # Check if this schema is an amber workspace tool
            if action_name in {"write_file", "run_command", "git_commit", "start_local_server", "run_project"}:
                return "AMBER"
            return "GREEN"
        try:
            policy = action_policy.classify_action(action_name)
            return policy.risk
        except Exception:
            return "RED"

    def execute_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Centrally dispatches tool execution with argument validation and error handling.
        Returns a dictionary containing 'status', 'result', and error details if any.
        """
        context = context or {}
        try:
            # 1. Native Application Management
            if tool_name in {"launch_app", "launch_calculator", "launch_camera", "launch_notepad", "launch_chrome", "launch_vscode", "launch_youtube"}:
                app_target = arguments.get("app_name") or arguments.get("app")
                if not app_target:
                    if tool_name == "launch_calculator":
                        app_target = "calculator"
                    elif tool_name == "launch_camera":
                        app_target = "camera"
                    elif tool_name == "launch_notepad":
                        app_target = "notepad"
                    elif tool_name == "launch_chrome":
                        app_target = "chrome"
                    elif tool_name == "launch_vscode":
                        app_target = "code"
                    elif tool_name == "launch_youtube":
                        app_target = "youtube"
                    else:
                        return {"status": "error", "message": "Missing 'app_name' parameter for launch_app."}

                res = pc_control.launch_application(app_target)
                return {"status": res.get("status", "success"), "result": res, "tool": tool_name}

            elif tool_name == "close_app":
                app_target = arguments.get("app_name") or arguments.get("app")
                if not app_target:
                    return {"status": "error", "message": "Missing 'app_name' parameter for close_app."}
                res = pc_control.close_application(app_target)
                return {"status": res.get("status", "success"), "result": res, "tool": tool_name}

            # 2. Volume & Audio Management
            elif tool_name == "change_volume":
                direction = arguments.get("direction", "up")
                steps = int(arguments.get("steps", 5))
                res = pc_control.change_volume(direction, steps)
                return {"status": res.get("status", "success"), "result": res, "tool": tool_name}

            elif tool_name == "set_volume":
                level = int(arguments.get("level", 50))
                res = pc_control.set_volume(level)
                return {"status": res.get("status", "success"), "result": res, "tool": tool_name}

            elif tool_name == "toggle_mute":
                res = pc_control.toggle_mute()
                return {"status": res.get("status", "success"), "result": res, "tool": tool_name}

            # 3. System Hardware & Telemetry
            elif tool_name in {"get_system_metrics", "system_status", "battery_status"}:
                res = pc_control.get_system_metrics()
                return {"status": "success", "result": res, "tool": tool_name}

            elif tool_name == "get_disk_space":
                drive_arg = arguments.get("drive")
                res = pc_control.get_disk_space(target_drive=drive_arg)
                return {"status": "success", "result": res, "tool": tool_name}

            elif tool_name == "list_running_processes":
                lim = int(arguments.get("limit", 15))
                sort_mem = bool(arguments.get("sort_by_memory", True))
                res = pc_control.list_running_processes(limit=lim, sort_by_memory=sort_mem)
                return {"status": "success", "result": res, "tool": tool_name}

            elif tool_name == "find_large_files":
                min_mb = int(arguments.get("min_size_mb", 100))
                max_res = int(arguments.get("max_results", 10))
                res = pc_control.find_large_files(min_size_mb=min_mb, max_results=max_res)
                return {"status": "success", "result": res, "tool": tool_name}

            elif tool_name == "open_folder":
                folder_arg = arguments.get("folder_path") or arguments.get("path") or arguments.get("folder", "")
                res = pc_control.open_folder(folder_arg)
                return {"status": res.get("status", "success"), "result": res, "tool": tool_name}

            # 4. Desktop Screenshot
            elif tool_name in {"capture_desktop_screenshot", "screenshot"}:
                res = pc_control.capture_desktop_screenshot()
                return {"status": res.get("status", "success"), "result": res, "tool": tool_name}

            # 5. File & Project Search
            elif tool_name == "search_user_files":
                query = arguments.get("query", "").strip()
                max_results = int(arguments.get("max_results", 15))
                res = pc_control.search_user_files(query, max_results=max_results)
                return {"status": res.get("status", "success"), "result": res, "tool": tool_name}

            elif tool_name in {"find_resume_files", "find_resume"}:
                found = pc_control.find_resume_files()
                return {
                    "status": "success",
                    "result": {"results": found, "count": len(found)},
                    "tool": tool_name,
                }

            elif tool_name == "open_file_path":
                fpath = arguments.get("file_path", "").strip()
                if not fpath:
                    return {"status": "error", "message": "Missing 'file_path' parameter."}
                res = pc_control.open_file_path(fpath)
                return {"status": res.get("status", "success"), "result": res, "tool": tool_name}

            # 6. Web Search
            elif tool_name in {"web_search", "web_search_in_browser", "search_web_in_browser"}:
                query = arguments.get("query", "").strip()
                browser_name = arguments.get("browser_name")
                engine = arguments.get("engine")
                res = pc_control.search_web_in_browser(query, browser_name=browser_name, engine=engine)
                return {"status": res.get("status", "success"), "result": res, "tool": tool_name}

            # 6b. Open YouTube
            elif tool_name in {"open_youtube", "launch_youtube"}:
                b_name = arguments.get("browser_name")
                res = pc_control.open_youtube(browser_name=b_name)
                return {"status": res.get("status", "success"), "result": res, "tool": tool_name}

            # 7. Run Project
            elif tool_name == "run_project":
                project_name = arguments.get("project_name", "").strip()
                project_path = arguments.get("project_path", "").strip()
                if not project_path and project_name:
                    # Look up path via search_user_files
                    search_res = pc_control.search_user_files(project_name, max_results=5)
                    dirs = [r for r in search_res.get("results", []) if r.get("is_project") or r.get("type") == "directory"]
                    if dirs:
                        project_path = dirs[0]["path"]

                return {
                    "status": "requires_approval",
                    "requires_approval": True,
                    "risk": "AMBER",
                    "project_name": project_name,
                    "project_path": project_path,
                    "message": f"Running project '{project_name}' requires execution approval.",
                    "tool": tool_name,
                }

            # 8. Browser Management
            elif tool_name == "launch_browser":
                b_name = arguments.get("browser_name")
                target_url = arguments.get("url")
                res = pc_control.launch_browser(b_name, target_url)
                return {"status": res.get("status", "success"), "result": res, "tool": tool_name}

            # 9. Application & Startup Diagnostics
            elif tool_name == "get_installed_applications":
                lim = int(arguments.get("limit", 50))
                filt = arguments.get("filter_term")
                res = pc_control.get_installed_applications(limit=lim, filter_term=filt)
                return {"status": "success", "result": res, "tool": tool_name}

            elif tool_name == "get_startup_applications":
                res = pc_control.get_startup_applications()
                return {"status": "success", "result": res, "tool": tool_name}

            # 10. Storage & Duplicate Intelligence
            elif tool_name == "find_duplicate_files":
                scan_d = arguments.get("directory")
                min_kb = int(arguments.get("min_size_kb", 50))
                max_r = int(arguments.get("max_results", 15))
                res = pc_control.find_duplicate_files(directory=scan_d, min_size_kb=min_kb, max_results=max_r)
                return {"status": "success", "result": res, "tool": tool_name}

            elif tool_name == "identify_temporary_files":
                max_r = int(arguments.get("max_results", 30))
                res = pc_control.identify_temporary_files(max_results=max_r)
                return {"status": "success", "result": res, "tool": tool_name}

            elif tool_name == "analyze_storage_cleanup":
                td = arguments.get("target_drive")
                res = pc_control.analyze_storage_cleanup(target_drive_or_path=td)
                return {"status": "success", "result": res, "tool": tool_name}

            elif tool_name == "analyze_project_folder":
                p_arg = arguments.get("project_path_or_name", "").strip()
                res = pc_control.analyze_project_folder(p_arg)
                return {"status": res.get("status", "success"), "result": res, "tool": tool_name}

            elif tool_name == "plan_system_diagnosis":
                from pc_control.task_planner import task_planner
                res = task_planner.plan_system_diagnosis()
                return {"status": "success", "result": res, "tool": tool_name}

            elif tool_name == "recycle_file_safely":
                fpath = arguments.get("file_path", "").strip()
                res = pc_control.recycle_file_safely(fpath)
                return {"status": res.get("status", "success"), "result": res, "tool": tool_name}

            else:
                return {
                    "status": "error",
                    "message": f"Unknown tool '{tool_name}' cannot be dispatched.",
                    "tool": tool_name,
                }

        except Exception as exc:
            return {
                "status": "error",
                "message": f"Tool execution failed for '{tool_name}': {str(exc)}",
                "tool": tool_name,
            }


tool_registry = ToolRegistry()
