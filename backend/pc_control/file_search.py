import os
import glob
import re
from typing import Dict, Any, List, Optional

USER_HOME = os.path.expanduser("~")
SEARCH_DIRS = [
    os.path.join(USER_HOME, "Downloads"),
    os.path.join(USER_HOME, "Documents"),
    os.path.join(USER_HOME, "Desktop"),
    os.path.join(USER_HOME, "desktop"),  # Case-safety
]

def _matches_query(name: str, query: str) -> bool:
    clean = query.strip().lower()
    if not clean:
        return False
    lower_name = name.lower()
    if clean in lower_name:
        return True
    terms = [t for t in re.split(r'[\s\-_]+', clean) if t]
    if len(terms) > 1 and all(t in lower_name for t in terms):
        return True
    no_space_query = clean.replace(" ", "").replace("-", "").replace("_", "")
    no_space_name = lower_name.replace(" ", "").replace("-", "").replace("_", "")
    if no_space_query and len(no_space_query) >= 3 and no_space_query in no_space_name:
        return True
    return False

def search_user_files(query: str, max_results: int = 15) -> Dict[str, Any]:
    """
    Search across common user directories (Downloads, Documents, Desktop)
    for files and project folders matching the query string.
    """
    clean_query = query.strip().lower()
    results: List[Dict[str, Any]] = []
    seen_paths = set()
    
    # Remove duplicate directories (e.g. Desktop vs desktop)
    checked_folders = []
    for d in SEARCH_DIRS:
        norm = os.path.normpath(d).lower()
        if norm not in checked_folders and os.path.exists(d):
            checked_folders.append(norm)

    for folder in SEARCH_DIRS:
        if not os.path.exists(folder):
            continue
        try:
            for root, dirs, files in os.walk(folder):
                rel_depth = root[len(folder):].count(os.sep)
                if rel_depth > 3:
                    dirs.clear()
                    continue

                # Check directories (e.g. project folders)
                for d in list(dirs):
                    if d.startswith(".") or d in {"node_modules", "__pycache__", "venv", ".venv"}:
                        continue
                    if _matches_query(d, clean_query):
                        full_dir = os.path.abspath(os.path.join(root, d))
                        norm_key = full_dir.lower()
                        if norm_key in seen_paths:
                            continue
                        seen_paths.add(norm_key)
                        is_proj = any(
                            os.path.exists(os.path.join(full_dir, m))
                            for m in ["package.json", "requirements.txt", "pom.xml", ".git", "Cargo.toml", "main.py", "app.py", "index.html"]
                        )
                        results.append({
                            "name": d,
                            "path": full_dir,
                            "type": "directory",
                            "is_project": is_proj,
                            "folder": os.path.basename(folder),
                        })
                        if len(results) >= max_results:
                            return {"status": "success", "results": results, "query": query}

                # Check files
                for f in files:
                    if _matches_query(f, clean_query):
                        full_path = os.path.abspath(os.path.join(root, f))
                        norm_key = full_path.lower()
                        if norm_key in seen_paths:
                            continue
                        seen_paths.add(norm_key)
                        try:
                            stat = os.stat(full_path)
                            results.append({
                                "name": f,
                                "path": full_path,
                                "type": "file",
                                "size_bytes": stat.st_size,
                                "modified": stat.st_mtime,
                                "folder": os.path.basename(folder)
                            })
                            if len(results) >= max_results:
                                return {"status": "success", "results": results, "query": query}
                        except Exception:
                            continue
        except Exception:
            continue
            
    return {"status": "success", "results": results, "query": query}

def find_resume_files() -> List[Dict[str, Any]]:
    """Look specifically for resume or CV files."""
    keywords = ["resume", "cv", "biodata"]
    found = []
    for kw in keywords:
        res = search_user_files(kw, max_results=5)
        for item in res.get("results", []):
            if item["path"] not in [x["path"] for x in found]:
                found.append(item)
    return found

def find_latest_file(ext: str = ".pdf") -> Optional[Dict[str, Any]]:
    """Find the most recently modified file with the given extension."""
    clean_ext = ext.lower()
    if not clean_ext.startswith("."):
        clean_ext = "." + clean_ext
        
    latest_item = None
    latest_mtime = 0
    
    for folder in SEARCH_DIRS:
        if not os.path.exists(folder):
            continue
        try:
            for root, dirs, files in os.walk(folder):
                rel_depth = root[len(folder):].count(os.sep)
                if rel_depth > 2:
                    dirs.clear()
                    continue
                for f in files:
                    if f.lower().endswith(clean_ext):
                        full_path = os.path.join(root, f)
                        try:
                            mtime = os.path.getmtime(full_path)
                            if mtime > latest_mtime:
                                latest_mtime = mtime
                                latest_item = {
                                    "name": f,
                                    "path": full_path,
                                    "modified": mtime,
                                    "folder": os.path.basename(folder)
                                }
                        except Exception:
                            continue
        except Exception:
            continue
            
    return latest_item

def create_user_folder(folder_name: str, base_dir: str = "Documents") -> Dict[str, Any]:
    """Create a folder in user Documents or Desktop."""
    clean_name = "".join(c for c in folder_name if c.isalnum() or c in (" ", "-", "_")).strip()
    target_base = os.path.join(USER_HOME, base_dir)
    target_path = os.path.join(target_base, clean_name)
    try:
        os.makedirs(target_path, exist_ok=True)
        return {"status": "success", "path": target_path, "message": f"Created folder '{clean_name}' at {target_path}"}
    except Exception as e:
        return {"status": "error", "message": f"Could not create folder: {str(e)}"}

def open_file_path(path: str) -> Dict[str, Any]:
    """Open a file or folder using native Windows default handler."""
    try:
        if not os.path.exists(path):
            return {"status": "error", "message": f"File not found: {path}"}
        os.startfile(path)
        return {"status": "success", "message": f"Opened {os.path.basename(path)}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
