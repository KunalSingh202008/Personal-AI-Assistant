"""
KELA General-Purpose Task Planner
Orchestrates multi-step investigation, diagnostic synthesis, storage recovery planning,
and context-aware follow-up resolution for Windows automation.
"""

import logging
from typing import Dict, Any, List, Optional
from pathlib import Path

from .system_ops import get_system_metrics, get_disk_space, list_running_processes, find_large_files
from .app_launcher import get_startup_applications, get_installed_applications
from .storage_analyzer import (
    analyze_storage_cleanup,
    find_duplicate_files,
    identify_temporary_files,
    analyze_project_folder,
)

logger = logging.getLogger("kela.planner")


class TaskPlanner:
    """
    Coordinates multi-step tool execution, telemetry evidence gathering,
    diagnostic bottleneck synthesis, and prioritized user action recommendations.
    """

    def plan_system_diagnosis(self, lang: str = "english") -> Dict[str, Any]:
        """
        Executes a 4-step diagnostic audit for:
        "Check my laptop and tell me why it is slow" / "Analyse my laptop and suggest improvements".
        1. CPU & RAM utilization.
        2. Disk storage and full drive detection.
        3. Top memory and process consumers.
        4. Startup applications impact.
        """
        # Step 1: System Metrics
        metrics_res = get_system_metrics()
        metrics = metrics_res.get("metrics", {})
        ram_pct = metrics.get("ram_usage_percent", 0.0)
        used_ram_gb = metrics.get("used_ram_gb", round(metrics.get("used_ram_mb", 0) / 1024, 1))
        total_ram_gb = metrics.get("total_ram_gb", round(metrics.get("total_ram_mb", 0) / 1024, 1))
        free_ram_gb = metrics.get("free_ram_gb", round(total_ram_gb - used_ram_gb, 1))

        # Step 2: Disk Space
        disk_res = get_disk_space()
        drives = disk_res.get("drives", [])
        almost_full = disk_res.get("almost_full_drives", [])

        # Step 3: Top memory processes
        procs_res = list_running_processes(limit=5, sort_by_memory=True)
        top_procs = procs_res.get("processes", [])

        # Step 4: Startup apps
        startup_res = get_startup_applications()
        startup_apps = startup_res.get("startup_applications", [])

        # --- Diagnostic Synthesis & Bottleneck Detection ---
        bottlenecks: List[Dict[str, str]] = []
        recommendations: List[str] = []

        # Check RAM
        if ram_pct >= 85.0:
            bottlenecks.append({
                "type": "RAM",
                "severity": "CRITICAL",
                "evidence": f"RAM is {ram_pct}% full ({used_ram_gb} GB used out of {total_ram_gb} GB). Only {free_ram_gb} GB free.",
            })
            if top_procs:
                top_names = ", ".join([f"{p['ProcessName']} ({p['MemoryMB']} MB)" for p in top_procs[:2]])
                recommendations.append(f"Close high-memory background applications: {top_names}.")
        elif ram_pct >= 70.0:
            bottlenecks.append({
                "type": "RAM",
                "severity": "WARNING",
                "evidence": f"RAM utilization is moderately high at {ram_pct}%.",
            })

        # Check Disk Space
        if almost_full:
            for af in almost_full:
                bottlenecks.append({
                    "type": "DISK",
                    "severity": "CRITICAL",
                    "evidence": f"{af['drive']} is {af['used_percent']}% full with only {af['free_gb']} GB available out of {af['total_gb']} GB.",
                })
                recommendations.append(f"Perform disk cleanup on drive {af['drive']} to free up space (less than {af['free_gb']} GB remaining).")
        elif drives:
            # Check primary C: drive
            c_dr = next((d for d in drives if d["drive"].upper().startswith("C")), None)
            if c_dr and c_dr["free_gb"] < 20.0:
                bottlenecks.append({
                    "type": "DISK",
                    "severity": "WARNING",
                    "evidence": f"C: drive has {c_dr['free_gb']} GB free.",
                })
                recommendations.append(f"Review large files and temporary cache on C: drive.")

        # Check Startup Applications
        high_impact_startups = [s for s in startup_apps if s.get("impact") == "High"]
        if len(startup_apps) >= 7 or high_impact_startups:
            bottlenecks.append({
                "type": "STARTUP",
                "severity": "MEDIUM",
                "evidence": f"{len(startup_apps)} startup applications active on boot.",
            })
            if high_impact_startups:
                start_names = ", ".join([s["name"] for s in high_impact_startups[:3]])
                recommendations.append(f"Disable unnecessary startup applications in Task Manager: {start_names}.")
            else:
                recommendations.append("Consider trimming startup applications to speed up boot and background responsiveness.")

        if not recommendations:
            recommendations.append("System performance is currently healthy. No severe resource bottlenecks detected.")

        # Format natural language narrative
        if lang == "hinglish":
            parts = []
            if bottlenecks:
                parts.append(f"Aapke laptop mein {len(bottlenecks)} mukhya bottlenecks mile:")
                for b in bottlenecks:
                    parts.append(f"- {b['type']}: {b['evidence']}")
                parts.append("Sudhar ke sujhav:")
                for r in recommendations:
                    parts.append(f"1. {r}")
                narrative = " ".join(parts)
            else:
                narrative = "Aapka laptop badhiya chal raha hai. RAM aur storage par koi bada dabav nahi hai."
        else:
            parts = []
            if bottlenecks:
                b_summary = ", ".join([f"{b['type']} ({b['evidence']})" for b in bottlenecks])
                parts.append(f"Diagnostic completed. Key bottlenecks detected: {b_summary}.")
                parts.append("Recommended actions: " + " ".join(recommendations))
                narrative = " ".join(parts)
            else:
                narrative = "Your laptop is operating normally with healthy RAM and disk margins. No major bottlenecks detected."

        return {
            "status": "success",
            "narrative": narrative,
            "bottlenecks": bottlenecks,
            "recommendations": recommendations,
            "telemetry": {
                "ram": {"used_gb": used_ram_gb, "total_gb": total_ram_gb, "percent": ram_pct, "free_gb": free_ram_gb},
                "drives": drives,
                "almost_full_drives": almost_full,
                "top_processes": top_procs,
                "startup_count": len(startup_apps),
            }
        }

    def plan_storage_cleanup(self, target_drive: Optional[str] = None, lang: str = "english") -> Dict[str, Any]:
        """
        Executes a comprehensive storage audit for:
        "Analyse my laptop and tell me which files are unnecessary" / "Which files can I safely review for cleanup?".
        """
        analysis = analyze_storage_cleanup(target_drive_or_path=target_drive)
        safe_mb = analysis.get("safe_recovery_mb", 0.0)
        review_mb = analysis.get("review_recovery_mb", 0.0)
        safe_items = analysis.get("safe_cleanup_candidates", [])
        review_items = analysis.get("review_candidates", [])

        safe_gb = round(safe_mb / 1024, 2)
        review_gb = round(review_mb / 1024, 2)
        total_gb = round((safe_mb + review_mb) / 1024, 2)

        if lang == "hinglish":
            resp = (
                f"Storage analysis poora hua! Kul {total_gb} GB space recover ho sakti hai. "
                f"{safe_gb} GB temporary cache aur logs mein hai jo surakshit roop se clear ki ja sakti hai, "
                f"aur {review_gb} GB purane installers aur duplicate files mein hai jise aap review kar sakte hain."
            )
        else:
            resp = (
                f"Storage analysis complete. You can recover approximately {total_gb} GB of space: "
                f"{safe_gb} GB from safe temporary files and caches, and "
                f"{review_gb} GB from old installers, archives, and duplicate files ready for review."
            )

        return {
            "status": "success",
            "narrative": resp,
            "total_recoverable_gb": total_gb,
            "safe_recovery_gb": safe_gb,
            "review_recovery_gb": review_gb,
            "safe_candidates": safe_items[:10],
            "review_candidates": review_items[:10],
            "all_candidates": (safe_items + review_items)[:20],
        }

    def handle_followup(
        self,
        query: str,
        context: Dict[str, Any],
        lang: str = "english"
    ) -> Optional[Dict[str, Any]]:
        """
        Resolves dynamic conversational follow-up questions referencing recent planner findings:
        - "Show me the largest one."
        - "What happens if I delete this?"
        - "Now check my other drive."
        """
        lower = query.lower().strip()

        # 1. "Show me the largest one" / "Sabse bada kaunsa hai"
        if any(p in lower for p in ["largest one", "show me the largest", "biggest one", "sabse bada", "largest file"]):
            candidates = context.get("last_storage_candidates") or context.get("last_large_files") or []
            if candidates:
                largest = max(candidates, key=lambda x: x.get("size_mb") or (x.get("size_bytes", 0) / (1024 * 1024)))
                sz = largest.get("size_mb") or round(largest.get("size_bytes", 0) / (1024 * 1024), 1)
                p = largest.get("path") or largest.get("name")
                cat = largest.get("category", "File")
                if lang == "hinglish":
                    resp = f"Sabse badi file hai: '{Path(p).name}' ({sz} MB, category: {cat}), path: {p}."
                else:
                    resp = f"The largest item found is '{Path(p).name}' ({sz} MB, category: {cat}) located at {p}."
                return {
                    "handled": True,
                    "response_text": resp,
                    "selected_entity": largest,
                    "entity_type": "file",
                }

        # 2. "What happens if I delete this?" / "Ise delete karne se kya hoga?"
        if any(p in lower for p in ["what happens if i delete", "kya hoga agar delete", "safe to delete", "delete kar sakte hain"]):
            last_file = context.get("last_file") or context.get("selected_entity")
            if last_file:
                fname = last_file.get("name") or Path(last_file.get("path", "")).name
                cat = last_file.get("category", "")
                reason = last_file.get("reason", "")
                risk = last_file.get("risk", "MEDIUM")

                if risk == "LOW" or "temp" in cat.lower() or "cache" in cat.lower():
                    exp = (
                        f"Deleting '{fname}' is SAFE. It is a temporary cache file created by Windows or applications; "
                        "deleting it will free disk space without affecting any personal documents or installed programs."
                    )
                elif "installer" in cat.lower() or fname.lower().endswith((".exe", ".msi")):
                    exp = (
                        f"Deleting '{fname}' is SAFE if the application is already installed. "
                        "The installer executable is only needed during initial setup. Deleting it will not uninstall the program."
                    )
                elif "duplicate" in cat.lower():
                    exp = (
                        f"Deleting this copy of '{fname}' is SAFE as an identical copy exists elsewhere in your files. "
                        "Your original data remains intact."
                    )
                else:
                    exp = (
                        f"Deleting '{fname}' requires careful review (Risk: {risk}). "
                        "If this is a personal document or project source file, deletion will permanently remove the data. "
                        "KELA never deletes files without your explicit approval."
                    )
                return {
                    "handled": True,
                    "response_text": exp,
                    "selected_entity": last_file,
                }

        # 3. "Now check my other drive" / "Dusra drive check karo"
        if any(p in lower for p in ["other drive", "dusra drive", "next drive", "check d drive", "d drive"]):
            disk_info = get_disk_space()
            drives = disk_info.get("drives", [])
            other_drives = [d for d in drives if not d["drive"].upper().startswith("C")]
            if other_drives:
                d = other_drives[0]
                if lang == "hinglish":
                    resp = f"Aapka {d['drive']} drive check kiya: {d['free_gb']} GB free hai kul {d['total_gb']} GB mein se ({d['used_percent']}% used)."
                else:
                    resp = f"Checked secondary drive {d['drive']}: {d['free_gb']} GB free out of {d['total_gb']} GB total ({d['used_percent']}% used)."
                return {
                    "handled": True,
                    "response_text": resp,
                    "drive": d["drive"],
                    "data": d,
                }
            else:
                resp = (
                    "Aapke laptop mein kewal ek hi main drive (C:) partition hai."
                    if lang == "hinglish" else
                    "Your laptop has only one primary partition mounted (C:). No other physical or logical drives were detected."
                )
                return {
                    "handled": True,
                    "response_text": resp,
                }

        return None


task_planner = TaskPlanner()
