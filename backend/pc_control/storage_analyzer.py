"""
KELA Storage & File Intelligence Analyzer
Provides deep Windows filesystem inspection, safe duplicate file detection,
temporary/cache file identification, project structure analysis, and safe reversible recycling.
"""

import os
import sys
import time
import hashlib
import shutil
import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional, Set
import ctypes
from ctypes import wintypes

USER_HOME = os.path.expanduser("~")
COMMON_USER_DIRS = [
    os.path.join(USER_HOME, "Downloads"),
    os.path.join(USER_HOME, "Documents"),
    os.path.join(USER_HOME, "Desktop"),
    os.path.join(USER_HOME, "Videos"),
    os.path.join(USER_HOME, "Music"),
    os.path.join(USER_HOME, "Pictures"),
]

# -----------------------------------------------------------------
# Win32 Recycle Bin Structure for Reversible Deletion
# -----------------------------------------------------------------
class SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [
        ('hwnd', wintypes.HWND),
        ('wFunc', wintypes.UINT),
        ('pFrom', wintypes.LPCWSTR),
        ('pTo', wintypes.LPCWSTR),
        ('fFlags', wintypes.WORD),
        ('fAnyOperationsAborted', wintypes.BOOL),
        ('hNameMappings', ctypes.c_void_p),
        ('lpszProgressTitle', wintypes.LPCWSTR),
    ]

FO_DELETE = 3
FOF_ALLOWUNDO = 0x0040
FOF_NOCONFIRMATION = 0x0010
FOF_NOERRORUI = 0x0400


def find_duplicate_files(
    directory: Optional[str] = None,
    min_size_kb: int = 50,
    max_results: int = 15
) -> Dict[str, Any]:
    """
    Detect genuine duplicate files using progressive 2-stage hashing (size -> partial 4KB -> full SHA-256).
    Safe, fast, and bounded to user folders.
    """
    scan_roots = [directory] if directory and os.path.exists(directory) else [
        os.path.join(USER_HOME, "Downloads"),
        os.path.join(USER_HOME, "Documents"),
        os.path.join(USER_HOME, "Desktop"),
    ]

    min_bytes = max(1024, min_size_kb * 1024)
    by_size: Dict[int, List[Path]] = {}
    files_scanned = 0

    for root_dir in scan_roots:
        if not os.path.exists(root_dir):
            continue
        for root, dirs, files in os.walk(root_dir):
            # Skip hidden, system, and heavy build folders
            dirs[:] = [d for d in dirs if not d.startswith(".") and d.lower() not in {"node_modules", "dist", "build", "venv", ".venv", "appdata"}]
            for f in files:
                if f.startswith("."):
                    continue
                p = Path(root) / f
                try:
                    st = p.stat()
                    if st.st_size >= min_bytes:
                        by_size.setdefault(st.st_size, []).append(p)
                        files_scanned += 1
                except (OSError, PermissionError):
                    continue
                if files_scanned > 2500:
                    break
            if files_scanned > 2500:
                break

    # Stage 1: Filter size collisions
    size_candidates = [paths for sz, paths in by_size.items() if len(paths) > 1]
    duplicate_groups = []
    total_recoverable_bytes = 0

    # Stage 2: 4KB prefix hash + full SHA-256 verification
    for paths in size_candidates:
        if len(duplicate_groups) >= max_results:
            break
        prefix_hashes: Dict[str, List[Path]] = {}
        for p in paths:
            try:
                with open(p, "rb") as fp:
                    prefix = fp.read(4096)
                    h_pref = hashlib.md5(prefix).hexdigest()
                    prefix_hashes.setdefault(h_pref, []).append(p)
            except (OSError, PermissionError):
                continue

        for h_pref, matched_paths in prefix_hashes.items():
            if len(matched_paths) > 1:
                # Full SHA-256 check
                full_hashes: Dict[str, List[Path]] = {}
                for mp in matched_paths:
                    try:
                        hasher = hashlib.sha256()
                        with open(mp, "rb") as fp:
                            while chunk := fp.read(65536):
                                hasher.update(chunk)
                        h_full = hasher.hexdigest()
                        full_hashes.setdefault(h_full, []).append(mp)
                    except (OSError, PermissionError):
                        continue

                for h_full, final_paths in full_hashes.items():
                    if len(final_paths) > 1:
                        sz = final_paths[0].stat().st_size
                        sz_mb = round(sz / (1024 * 1024), 2)
                        recoverable_sz = sz * (len(final_paths) - 1)
                        total_recoverable_bytes += recoverable_sz

                        items = []
                        for fp in final_paths:
                            try:
                                mtime = datetime.datetime.fromtimestamp(fp.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
                            except OSError:
                                mtime = "Unknown"
                            items.append({
                                "path": str(fp),
                                "filename": fp.name,
                                "modified": mtime,
                            })

                        duplicate_groups.append({
                            "hash": h_full[:16],
                            "size_bytes": sz,
                            "size_mb": sz_mb,
                            "count": len(final_paths),
                            "recoverable_mb": round(recoverable_sz / (1024 * 1024), 2),
                            "files": items,
                        })
                        if len(duplicate_groups) >= max_results:
                            break

    return {
        "status": "success",
        "scanned_files": files_scanned,
        "duplicate_groups_count": len(duplicate_groups),
        "total_recoverable_mb": round(total_recoverable_bytes / (1024 * 1024), 2),
        "duplicate_groups": duplicate_groups,
    }


def identify_temporary_files(max_results: int = 30) -> Dict[str, Any]:
    """
    Locates temporary files, error logs, and cache artifacts in %TEMP% and user directories.
    """
    temp_roots = [
        os.environ.get("TEMP", os.path.join(USER_HOME, "AppData", "Local", "Temp")),
        os.path.join(USER_HOME, "AppData", "Local", "CrashDumps"),
    ]

    temp_files = []
    total_bytes = 0

    for tr in temp_roots:
        if not tr or not os.path.exists(tr):
            continue
        try:
            for entry in os.scandir(tr):
                if entry.is_file(follow_symlinks=False):
                    try:
                        sz = entry.stat().st_size
                        if sz > 1024 * 50:  # > 50KB
                            mtime = datetime.datetime.fromtimestamp(entry.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
                            total_bytes += sz
                            temp_files.append({
                                "path": entry.path,
                                "name": entry.name,
                                "size_bytes": sz,
                                "size_mb": round(sz / (1024 * 1024), 2),
                                "modified": mtime,
                                "category": "Temporary / Cache",
                                "risk": "LOW",
                                "reason": "Standard Windows application temporary cache file.",
                            })
                    except (OSError, PermissionError):
                        continue
                if len(temp_files) > 100:
                    break
        except (OSError, PermissionError):
            continue

    temp_files.sort(key=lambda x: x["size_bytes"], reverse=True)
    return {
        "status": "success",
        "total_count": len(temp_files),
        "total_temp_mb": round(total_bytes / (1024 * 1024), 2),
        "temporary_files": temp_files[:max_results],
    }


def analyze_storage_cleanup(target_drive_or_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Genuine multi-category storage analysis workflow.
    Answers: "Analyse my laptop and tell me which files are unnecessary" / "Which files can I safely review for cleanup?"
    Categorizes candidates into safe cleanup (LOW risk) vs review-recommended (MEDIUM/HIGH risk).
    Never deletes anything automatically.
    """
    # 1. Inspect Temporary files
    temp_res = identify_temporary_files(max_results=15)
    temp_items = temp_res.get("temporary_files", [])

    # 2. Inspect Duplicate files in Downloads & Documents
    dupes_res = find_duplicate_files(max_results=10)
    dupe_groups = dupes_res.get("duplicate_groups", [])

    # 3. Inspect Old Installers and Archives in Downloads
    downloads_dir = os.path.join(USER_HOME, "Downloads")
    installer_archive_items = []
    if os.path.exists(downloads_dir):
        now = time.time()
        for root, dirs, files in os.walk(downloads_dir):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for f in files:
                p = Path(root) / f
                ext = p.suffix.lower()
                if ext in {".exe", ".msi", ".zip", ".rar", ".tar", ".gz", ".7z", ".iso"}:
                    try:
                        st = p.stat()
                        age_days = (now - st.st_mtime) / 86400.0
                        if st.st_size > 5 * 1024 * 1024:  # > 5 MB
                            mtime = datetime.datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M")
                            if ext in {".exe", ".msi"}:
                                cat = "Installer"
                                reason = f"Installer file downloaded {int(age_days)} days ago; safe to remove if already installed."
                                risk = "LOW" if age_days > 7 else "MEDIUM"
                            else:
                                cat = "Archive"
                                reason = f"Compressed archive ({ext}) taking {round(st.st_size/(1024*1024), 1)} MB; review if contents are already extracted."
                                risk = "MEDIUM"

                            installer_archive_items.append({
                                "path": str(p),
                                "name": p.name,
                                "size_bytes": st.st_size,
                                "size_mb": round(st.st_size / (1024 * 1024), 2),
                                "modified": mtime,
                                "category": cat,
                                "reason": reason,
                                "risk": risk,
                            })
                    except (OSError, PermissionError):
                        continue
            if len(installer_archive_items) > 30:
                break

    installer_archive_items.sort(key=lambda x: x["size_bytes"], reverse=True)

    # 4. Synthesize Recommendations
    safe_cleanup_candidates = []
    review_candidates = []
    total_safe_recovery_mb = 0.0
    total_review_recovery_mb = 0.0

    # Add temp files to safe
    for t in temp_items:
        safe_cleanup_candidates.append(t)
        total_safe_recovery_mb += t["size_mb"]

    # Add duplicate extras to review
    for dg in dupe_groups:
        files = dg["files"]
        if len(files) > 1:
            for extra in files[1:]:
                item = {
                    "path": extra["path"],
                    "name": extra["filename"],
                    "size_bytes": dg["size_bytes"],
                    "size_mb": dg["size_mb"],
                    "modified": extra["modified"],
                    "category": "Duplicate",
                    "reason": f"Identical duplicate of '{files[0]['filename']}'.",
                    "risk": "LOW",
                }
                review_candidates.append(item)
                total_review_recovery_mb += dg["size_mb"]

    # Add installers and archives
    for ia in installer_archive_items:
        if ia["risk"] == "LOW":
            safe_cleanup_candidates.append(ia)
            total_safe_recovery_mb += ia["size_mb"]
        else:
            review_candidates.append(ia)
            total_review_recovery_mb += ia["size_mb"]

    # Top recommendations ranked by recovery potential
    safe_cleanup_candidates.sort(key=lambda x: x["size_mb"], reverse=True)
    review_candidates.sort(key=lambda x: x["size_mb"], reverse=True)

    return {
        "status": "success",
        "total_recoverable_mb": round(total_safe_recovery_mb + total_review_recovery_mb, 2),
        "safe_recovery_mb": round(total_safe_recovery_mb, 2),
        "review_recovery_mb": round(total_review_recovery_mb, 2),
        "safe_cleanup_count": len(safe_cleanup_candidates),
        "review_count": len(review_candidates),
        "safe_cleanup_candidates": safe_cleanup_candidates[:15],
        "review_candidates": review_candidates[:15],
    }


def analyze_project_folder(project_path_or_name: str) -> Dict[str, Any]:
    """
    Deeply analyzes a project directory: tech stack, Git health, dependencies,
    total file count, directory size, large files, and heavy build folders.
    """
    clean_target = project_path_or_name.strip()
    target_path = Path(clean_target)

    # Resolve if only project name was provided
    if not target_path.exists():
        search_dirs = [
            Path(USER_HOME) / "Documents",
            Path(USER_HOME) / "Desktop",
            Path(USER_HOME) / "Downloads",
            Path.cwd(),
        ]
        found = None
        for sdir in search_dirs:
            cand = sdir / clean_target
            if cand.exists() and cand.is_dir():
                found = cand
                break
        if not found:
            # Fuzzy match
            for sdir in search_dirs:
                if sdir.exists():
                    for sub in sdir.iterdir():
                        if sub.is_dir() and clean_target.lower() in sub.name.lower():
                            found = sub
                            break
                    if found:
                        break
        if found:
            target_path = found
        else:
            return {
                "status": "error",
                "message": f"Project folder '{project_path_or_name}' could not be located.",
            }

    # 1. Tech stack detection
    tech_stack = []
    dep_files = []
    if (target_path / "package.json").exists():
        tech_stack.append("Node.js / JavaScript / TypeScript")
        dep_files.append("package.json")
    if (target_path / "requirements.txt").exists() or (target_path / "pyproject.toml").exists():
        tech_stack.append("Python")
        dep_files.append("requirements.txt" if (target_path / "requirements.txt").exists() else "pyproject.toml")
    if (target_path / "Cargo.toml").exists():
        tech_stack.append("Rust / Cargo")
        dep_files.append("Cargo.toml")
    if (target_path / "pom.xml").exists() or (target_path / "build.gradle").exists():
        tech_stack.append("Java / Kotlin")
        dep_files.append("pom.xml" if (target_path / "pom.xml").exists() else "build.gradle")
    if not tech_stack:
        tech_stack.append("General Software Project")

    # 2. Git inspection
    git_dir = target_path / ".git"
    is_git = git_dir.exists() and git_dir.is_dir()
    git_info = {"is_git_repository": is_git}
    if is_git:
        try:
            head_file = git_dir / "HEAD"
            if head_file.exists():
                head_content = head_file.read_text(encoding="utf-8").strip()
                git_info["branch"] = head_content.split("/")[-1] if "/" in head_content else head_content
        except Exception:
            git_info["branch"] = "main"

    # 3. File count, size, build folders, large files
    total_bytes = 0
    total_files = 0
    build_folders = []
    large_files = []

    for root, dirs, files in os.walk(target_path):
        rel_root = os.path.relpath(root, target_path)
        # Track build folder sizes
        for d in dirs:
            if d.lower() in {"node_modules", "dist", "build", "target", ".next", ".venv", "venv", "__pycache__"}:
                build_folders.append(os.path.join(rel_root, d) if rel_root != "." else d)

        for f in files:
            p = Path(root) / f
            try:
                sz = p.stat().st_size
                total_bytes += sz
                total_files += 1
                if sz > 10 * 1024 * 1024:  # > 10MB
                    large_files.append({
                        "name": f,
                        "path": str(p),
                        "size_mb": round(sz / (1024 * 1024), 2),
                    })
            except (OSError, PermissionError):
                continue
        if total_files > 10000:
            break

    large_files.sort(key=lambda x: x["size_mb"], reverse=True)

    recommendations = []
    if build_folders:
        recommendations.append(f"Contains build/dependency directories ({', '.join(build_folders[:3])}). Run cleanup scripts if archiving.")
    if large_files:
        recommendations.append(f"Found {len(large_files)} large file(s) exceeding 10 MB inside project.")
    if not is_git:
        recommendations.append("Project is not tracked with Git version control. Consider running 'git init'.")
    if not recommendations:
        recommendations.append("Project structure is clean and well-organized.")

    return {
        "status": "success",
        "project_name": target_path.name,
        "project_path": str(target_path.resolve()),
        "tech_stack": tech_stack,
        "manifest_files": dep_files,
        "git_status": git_info,
        "total_files": total_files,
        "total_size_mb": round(total_bytes / (1024 * 1024), 2),
        "build_directories": build_folders[:5],
        "large_files": large_files[:5],
        "recommendations": recommendations,
    }


def recycle_file_safely(file_path: str) -> Dict[str, Any]:
    """
    Safely moves a file to the native Windows Recycle Bin using SHFileOperationW.
    Reversible and safe. Requires explicit user approval before invocation.
    """
    clean_path = str(Path(file_path).resolve())
    if not os.path.exists(clean_path):
        return {"status": "error", "message": f"File does not exist: {file_path}", "verified": False}

    # Use native Windows Recycle Bin
    try:
        pfrom = clean_path + "\0\0"
        op = SHFILEOPSTRUCTW()
        op.wFunc = FO_DELETE
        op.pFrom = pfrom
        op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_NOERRORUI

        ret = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
        if ret == 0 and not os.path.exists(clean_path):
            return {
                "status": "success",
                "message": f"Moved to Windows Recycle Bin: {os.path.basename(clean_path)}",
                "verified": True,
                "file_path": clean_path,
                "reversible": True,
            }
    except Exception as ex:
        pass

    # Fallback to quarantine folder in ~/.kela/quarantine
    try:
        quarantine_dir = Path.home() / ".kela" / "quarantine"
        quarantine_dir.mkdir(parents=True, exist_ok=True)
        dest = quarantine_dir / f"{int(time.time())}_{os.path.basename(clean_path)}"
        shutil.move(clean_path, dest)
        return {
            "status": "success",
            "message": f"Moved to safe quarantine: {dest.name}",
            "verified": True,
            "file_path": clean_path,
            "quarantine_path": str(dest),
            "reversible": True,
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to safely recycle file: {str(e)}",
            "verified": False,
        }
