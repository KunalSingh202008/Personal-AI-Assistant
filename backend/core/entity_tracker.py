"""
Entity and Pronoun Tracker for KELA AI Platform.
Maintains state across conversation turns to resolve pronouns ("it", "that", "the project", "the file", "the app")
and contextual references to applications, files, projects, and queries.
"""

import os
import re
import threading
from typing import Dict, Any, Optional, Tuple, List


class EntityTracker:
    """
    Thread-safe contextual entity tracker managing active projects, files,
    applications, and pronoun resolution across conversation sessions.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._state: Dict[int, Dict[str, Any]] = {}

    def get_context(self, conversation_id: Optional[int]) -> Dict[str, Any]:
        if conversation_id is None:
            return {}
        with self._lock:
            return dict(self._state.get(conversation_id, {}))

    def update_entities(
        self,
        conversation_id: Optional[int],
        last_project: Optional[Dict[str, Any]] = None,
        last_file: Optional[Dict[str, Any]] = None,
        last_folder: Optional[Dict[str, Any]] = None,
        last_app: Optional[str] = None,
        last_query: Optional[str] = None,
        last_action: Optional[str] = None,
        last_result: Optional[Any] = None,
        last_language: Optional[str] = None,
        last_entity_type: Optional[str] = None,
    ):
        if conversation_id is None:
            return
        with self._lock:
            if conversation_id not in self._state:
                self._state[conversation_id] = {}
            st = self._state[conversation_id]
            if last_project is not None:
                st["last_project"] = last_project
            if last_file is not None:
                st["last_file"] = last_file
            if last_folder is not None:
                st["last_folder"] = last_folder
            if last_app is not None:
                st["last_app"] = last_app
            if last_query is not None:
                st["last_query"] = last_query
            if last_action is not None:
                st["last_action"] = last_action
            if last_result is not None:
                st["last_result"] = last_result
            if last_language is not None:
                st["last_language"] = last_language
            if last_entity_type is not None:
                st["last_entity_type"] = last_entity_type

    def update_from_action_result(
        self,
        conversation_id: Optional[int],
        action_name: str,
        params: Dict[str, Any],
        result: Dict[str, Any],
        lang: str = "english",
    ):
        if conversation_id is None:
            return
        with self._lock:
            if conversation_id not in self._state:
                self._state[conversation_id] = {}
            st = self._state[conversation_id]
            st["last_action"] = action_name
            st["last_result"] = result
            st["last_language"] = lang

            # Application actions
            if action_name in {
                "launch_app", "close_app", "launch_camera", "launch_calculator",
                "launch_notepad", "launch_chrome", "launch_vscode", "launch_youtube"
            }:
                app = params.get("app_name") or params.get("app")
                if not app and action_name.startswith("launch_"):
                    app = action_name[len("launch_"):]
                if app:
                    st["last_app"] = app
                    st["last_entity_type"] = "app"

            # Search operations
            elif action_name == "search_user_files":
                q = params.get("query", "")
                if q:
                    st["last_query"] = q
                res_list = result.get("results", []) if isinstance(result, dict) else []
                # Project directories prioritize
                projects = [r for r in res_list if r.get("is_project") or r.get("type") == "directory"]
                if projects:
                    st["last_project"] = {
                        "name": projects[0]["name"],
                        "path": projects[0]["path"],
                        "folder": projects[0].get("folder"),
                    }
                    st["last_entity_type"] = "project"
                files = [r for r in res_list if r.get("type") == "file"]
                if files:
                    st["last_file"] = {
                        "name": files[0]["name"],
                        "path": files[0]["path"],
                        "folder": files[0].get("folder"),
                    }
                    if not projects:
                        st["last_entity_type"] = "file"

            elif action_name in {"find_resume_files", "find_resume"}:
                res_list = result if isinstance(result, list) else result.get("results", [])
                if res_list:
                    st["last_file"] = {
                        "name": res_list[0]["name"],
                        "path": res_list[0]["path"],
                        "folder": res_list[0].get("folder"),
                    }
                    st["last_entity_type"] = "file"

            elif action_name == "open_folder":
                fpath = result.get("path") or params.get("folder_path", "")
                if fpath:
                    st["last_folder"] = {
                        "name": os.path.basename(fpath),
                        "path": fpath,
                    }
                    st["last_entity_type"] = "folder"

            elif action_name == "open_file_path":
                fpath = params.get("file_path", "")
                if fpath:
                    st["last_file"] = {
                        "name": os.path.basename(fpath),
                        "path": fpath,
                    }
                    st["last_entity_type"] = "file"

    def resolve_pronouns(
        self,
        text: str,
        conversation_id: Optional[int],
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Inspects text for anaphora/pronouns ('it', 'that', 'the project', 'ise', 'usko')
        and resolves them using tracked entities from the conversation.
        Returns:
            (resolved_text, metadata)
        """
        clean = text.strip()
        lower = clean.lower()
        ctx = self.get_context(conversation_id)
        meta: Dict[str, Any] = {
            "original_text": clean,
            "resolved": False,
            "resolved_target": None,
            "target_type": None,
        }

        # 1. "run it" / "start it" / "execute it" / "run this project" / "chalao ise"
        run_pronoun_match = re.search(
            r'\b(?:run|start|execute|launch|chalao)\s+(?:it|that|this|the project|that project|this project|ise|isko|usko)\b',
            lower
        ) or re.search(
            r'\b(?:ise|isko|usko)\s+(?:run karo|chalao|start karo)\b',
            lower
        ) or lower in {"run it", "start it", "chalao ise", "ise chalao", "run that", "run project", "run the project", "run this project"}

        if run_pronoun_match:
            if ctx.get("last_project"):
                proj = ctx["last_project"]
                resolved_text = f"run project {proj['name']}"
                meta["resolved"] = True
                meta["resolved_target"] = proj
                meta["target_type"] = "project"
                return resolved_text, meta
            elif ctx.get("last_app"):
                app = ctx["last_app"]
                resolved_text = f"open {app}"
                meta["resolved"] = True
                meta["resolved_target"] = app
                meta["target_type"] = "app"
                return resolved_text, meta

        # 2. "open it" / "kholo ise" / "open that" / "open the file" / "open the document" / "open the project"
        open_pronoun_match = re.search(
            r'\b(?:open|kholo|dekho|view)\s+(?:it|that|this|the file|that file|the document|the project|this project|ise|isko|usko)\b',
            lower
        ) or re.search(
            r'\b(?:ise|isko|usko)\s+(?:kholo|open karo|dekho)\b',
            lower
        ) or lower in {"open it", "kholo ise", "ise kholo", "open that", "open the file", "open the project", "open this project"}

        if open_pronoun_match:
            entity_type = ctx.get("last_entity_type")
            if entity_type == "project" and ctx.get("last_project"):
                proj = ctx["last_project"]
                resolved_text = f"open folder {proj['path']}"
                meta["resolved"] = True
                meta["resolved_target"] = proj
                meta["target_type"] = "project"
                return resolved_text, meta
            elif entity_type == "folder" and ctx.get("last_folder"):
                f = ctx["last_folder"]
                resolved_text = f"open folder {f['path']}"
                meta["resolved"] = True
                meta["resolved_target"] = f
                meta["target_type"] = "folder"
                return resolved_text, meta
            elif entity_type == "file" and ctx.get("last_file"):
                f = ctx["last_file"]
                resolved_text = f"open file {f['path']}"
                meta["resolved"] = True
                meta["resolved_target"] = f
                meta["target_type"] = "file"
                return resolved_text, meta
            elif ctx.get("last_project"):
                proj = ctx["last_project"]
                resolved_text = f"open folder {proj['path']}"
                meta["resolved"] = True
                meta["resolved_target"] = proj
                meta["target_type"] = "project"
                return resolved_text, meta
            elif ctx.get("last_folder"):
                f = ctx["last_folder"]
                resolved_text = f"open folder {f['path']}"
                meta["resolved"] = True
                meta["resolved_target"] = f
                meta["target_type"] = "folder"
                return resolved_text, meta
            elif ctx.get("last_file"):
                f = ctx["last_file"]
                resolved_text = f"open file {f['path']}"
                meta["resolved"] = True
                meta["resolved_target"] = f
                meta["target_type"] = "file"
                return resolved_text, meta
            elif ctx.get("last_app"):
                app = ctx["last_app"]
                resolved_text = f"open {app}"
                meta["resolved"] = True
                meta["resolved_target"] = app
                meta["target_type"] = "app"
                return resolved_text, meta

        # 3. "close it" / "band karo ise" / "close that"
        close_pronoun_match = re.search(
            r'\b(?:close|quit|exit|band karo)\s+(?:it|that|this|the app|that app|ise|isko|usko)\b',
            lower
        ) or re.search(
            r'\b(?:ise|isko|usko)\s+(?:band karo|close karo)\b',
            lower
        ) or lower in {"close it", "band karo ise", "ise band karo", "close that"}

        if close_pronoun_match and ctx.get("last_app"):
            app = ctx["last_app"]
            resolved_text = f"close {app}"
            meta["resolved"] = True
            meta["resolved_target"] = app
            meta["target_type"] = "app"
            return resolved_text, meta

        # 4. "where is it" / "where was it saved" / "kahan hai yeh"
        where_pronoun_match = re.search(
            r'\b(?:where is|where was|kahan hai)\s+(?:it|that|the file|the project|yeh|woh|ye)\b',
            lower
        )
        if where_pronoun_match:
            if ctx.get("last_project"):
                proj = ctx["last_project"]
                resolved_text = f"where is {proj['name']}"
                meta["resolved"] = True
                meta["resolved_target"] = proj
                meta["target_type"] = "project"
                return resolved_text, meta
            elif ctx.get("last_file"):
                f = ctx["last_file"]
                resolved_text = f"where is {f['name']}"
                meta["resolved"] = True
                meta["resolved_target"] = f
                meta["target_type"] = "file"
                return resolved_text, meta

        return clean, meta

    def clear(self, conversation_id: Optional[int] = None):
        with self._lock:
            if conversation_id is not None:
                self._state.pop(conversation_id, None)
            else:
                self._state.clear()


entity_tracker = EntityTracker()
