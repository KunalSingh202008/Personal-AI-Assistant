import re
import os
import datetime
import urllib.parse
import json
import httpx
from typing import Dict, Any, Optional, Tuple

from pc_control import (
    launch_application,
    close_application,
    change_volume,
    set_volume,
    toggle_mute,
    get_system_metrics,
    capture_desktop_screenshot,
    search_user_files,
    find_resume_files,
    find_latest_file,
    create_user_folder,
    open_file_path,
    search_web_in_browser,
)

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5-coder:7b")

WAKE_WORDS = ["hey kela", "kela", "ok kela", "hello kela", "sun kela", "arrey kela"]

HINDI_INDICATORS = [
    "kholo", "chalao", "band karo", "badhao", "kam karo", "batao", "kya", "haal",
    "kaise", "samay", "kitna", "hai", "aaj", "lo", "kar do", "sun", "dhundo", "mera", "meri"
]

def is_wake_word_present(text: str) -> Tuple[bool, str]:
    """Check if 'Hey KELA' or wake word prefixes the query, stripping it if present."""
    clean = text.strip()
    lower = clean.lower()
    for ww in WAKE_WORDS:
        if lower.startswith(ww):
            stripped = clean[len(ww):].strip(" ,:!.-")
            return True, stripped
    return False, clean

def detect_language(text: str) -> str:
    """Detect if utterance is primarily Hindi/Hinglish or English."""
    lower = text.lower()
    matches = sum(1 for word in HINDI_INDICATORS if re.search(r'\b' + re.escape(word) + r'\b', lower))
    return "hinglish" if matches >= 1 else "english"

async def ask_voice_llm(prompt: str, lang: str = "english") -> str:
    """Fast conversational query to Ollama for voice interaction (max 30 tokens, 3.5s timeout)."""
    system_prompt = (
        "You are KELA, an ultra-fast voice assistant for Kunal Singh. "
        "Answer in ONE short, natural spoken sentence (under 25 words). "
        "Never use markdown, lists, code, or quotes."
    )
    
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ],
        "stream": False,
        "options": {
            "temperature": 0.4,
            "num_predict": 30
        }
    }
    
    try:
        async with httpx.AsyncClient(timeout=3.5) as client:
            resp = await client.post(f"{OLLAMA_URL}/api/chat", json=payload)
            if resp.status_code == 200:
                data = resp.json()
                content = data.get("message", {}).get("content", "").strip()
                content = re.sub(r'[*_#`[\]()"\n]', ' ', content).strip()
                if content:
                    return content
    except Exception:
        pass
        
    return "I am right here with you, Kunal. How can I help next?" if lang == "english" else "Haan Kunal, main sun raha hoon. Kya karna hai?"

async def dispatch_voice_command(text: str) -> Dict[str, Any]:
    """
    Sub-millisecond unified voice command router.
    Executes native C/Win32 tools and returns instant conversational responses.
    """
    _, query = is_wake_word_present(text)
    clean = query.strip()
    lower = clean.lower()
    lang = detect_language(lower)
    
    if not clean:
        resp = "Haan boliye Kunal, main sun raha hoon." if lang == "hinglish" else "Yes Kunal, I'm listening."
        return {"handled": True, "fast_path": True, "response_text": resp, "action": "greeting", "lang": lang}

    # 1. Session control: Stop / Exit / Pause
    if re.search(r'\b(stop listening|stop session|bye kela|bye|so jao|exit voice|shut down voice)\b', lower):
        resp = "Alvida Kunal, voice session band kar raha hoon." if lang == "hinglish" else "Stopping listening. Call me whenever you need me, Kunal."
        return {"handled": True, "fast_path": True, "response_text": resp, "action": "stop_listening", "stop_session": True, "lang": lang}

    if re.search(r'\b(pause listening|pause session|ruk jao|wait a minute)\b', lower):
        resp = "Voice listening pause kar di hai." if lang == "hinglish" else "Listening paused. Say resume or click the mic when you're ready."
        return {"handled": True, "fast_path": True, "response_text": resp, "action": "pause_listening", "pause_session": True, "lang": lang}

    # 2. Assistant Identity & Capabilities
    if re.search(r'\b(who are you|what is your name|tum kaun ho|naam kya hai)\b', lower):
        resp = (
            "Main KELA hoon, aapka personal voice assistant aur AI operating system."
            if lang == "hinglish" else
            "I am KELA, your personal voice assistant and autonomous operating system."
        )
        return {"handled": True, "fast_path": True, "response_text": resp, "action": "assistant_identity", "lang": lang}

    if re.search(r'\b(what can you do|kya kar sakte ho|help me|features)\b', lower):
        resp = (
            "Main aapke apps launch kar sakta hoon, volume aur battery control kar sakta hoon, files aur web search kar sakta hoon, aur aapke sawalon ke jawab de sakta hoon."
            if lang == "hinglish" else
            "I can launch your applications, manage system audio, search your local files, browse the web, and answer your questions."
        )
        return {"handled": True, "fast_path": True, "response_text": resp, "action": "help", "lang": lang}

    # 3. Personal Context & User Profile (Section 6)
    if re.search(r'\b(who am i|mera naam kya hai|do you know me|who is kunal)\b', lower):
        resp = (
            "Aap Kunal Singh hain, B.Tech Computer Science ke student aur AI developer. Aap Nexus AI, StreeSure, aur ClassTrack AI par kaam kar rahe hain."
            if lang == "hinglish" else
            "You are Kunal Singh, a B.Tech Computer Science student and AI developer building Nexus AI, StreeSure, and ClassTrack AI."
        )
        return {"handled": True, "fast_path": True, "response_text": resp, "action": "identity", "lang": lang}

    if re.search(r'\b(my projects|tell me about my projects|current projects|mere projects)\b', lower):
        resp = (
            "Aapke core projects hain: Nexus AI, jo aapka autonomous personal AI operating system hai; StreeSure; aur ClassTrack AI."
            if lang == "hinglish" else
            "Your core projects are Nexus AI, your personal AI operating system, StreeSure for safety analytics, and ClassTrack AI for student workflows."
        )
        return {"handled": True, "fast_path": True, "response_text": resp, "action": "projects_info", "lang": lang}

    if re.search(r'\b(hello|hi|hey|kya haal hai|kaise ho|how are you)\b', lower) and len(clean.split()) <= 4:
        resp = "Main badhiya hoon Kunal! Boliye, kis project ya task par kaam karein?" if lang == "hinglish" else "Hello Kunal! I am doing great. What would you like to work on next?"
        return {"handled": True, "fast_path": True, "response_text": resp, "action": "greeting", "lang": lang}

    # 4. Instant Audio / Volume Controls (<0.1ms via ctypes)
    if re.search(r'\b(volume up|increase volume|louder|awaz badhao|volume badhao)\b', lower):
        res = change_volume("up", 5)
        resp = "Volume badha diya hai." if lang == "hinglish" else "Volume increased."
        return {"handled": True, "fast_path": True, "response_text": resp, "action": "volume_up", "data": res, "lang": lang}

    if re.search(r'\b(volume down|decrease volume|softer|awaz kam karo|volume kam karo)\b', lower):
        res = change_volume("down", 5)
        resp = "Volume kam kar diya hai." if lang == "hinglish" else "Volume decreased."
        return {"handled": True, "fast_path": True, "response_text": resp, "action": "volume_down", "data": res, "lang": lang}

    if re.search(r'\b(mute|unmute|awaz band karo|chup ho jao)\b', lower):
        res = toggle_mute()
        resp = "Audio mute toggle kar diya." if lang == "hinglish" else "Audio mute toggled."
        return {"handled": True, "fast_path": True, "response_text": resp, "action": "toggle_mute", "data": res, "lang": lang}

    vol_match = re.search(r'(?:set volume to|volume)\s+(\d{1,3})\s*(?:percent|%)?', lower)
    if vol_match:
        target_val = int(vol_match.group(1))
        res = set_volume(target_val)
        resp = f"Volume {target_val} percent par set kar diya." if lang == "hinglish" else f"Volume set to {target_val}%."
        return {"handled": True, "fast_path": True, "response_text": resp, "action": "set_volume", "data": res, "lang": lang}

    # 5. Native App Launchers (Camera, Chrome, VS Code, Calculator, Notepad, Spotify, YouTube, Explorer)
    if re.search(r'\b(open camera|camera kholo|webcam kholo)\b', lower):
        res = launch_application("camera")
        resp = "Camera khol diya hai." if lang == "hinglish" else "Opening your camera."
        return {"handled": True, "fast_path": True, "response_text": resp, "action": "launch_camera", "data": res, "lang": lang}

    if re.search(r'\b(open youtube|youtube kholo|play youtube)\b', lower):
        res = launch_application("youtube")
        resp = "YouTube open kar diya hai." if lang == "hinglish" else "Opening YouTube in your browser."
        return {"handled": True, "fast_path": True, "response_text": resp, "action": "launch_youtube", "data": res, "lang": lang}

    if re.search(r'\b(open (?:the )?(?:browser|chrome|google chrome)|chrome kholo|browser kholo)\b', lower):
        res = launch_application("chrome")
        resp = "Google Chrome khol diya hai." if lang == "hinglish" else "Opening Google Chrome."
        return {"handled": True, "fast_path": True, "response_text": resp, "action": "launch_chrome", "data": res, "lang": lang}

    if re.search(r'\b(open (?:vs code|vscode|code editor)|code kholo)\b', lower):
        res = launch_application("code")
        resp = "VS Code khol diya hai." if lang == "hinglish" else "Opening VS Code."
        return {"handled": True, "fast_path": True, "response_text": resp, "action": "launch_vscode", "data": res, "lang": lang}

    if re.search(r'\b(open (?:calculator|calc)|calculator kholo|calc kholo)\b', lower):
        res = launch_application("calculator")
        resp = "Calculator khol diya hai." if lang == "hinglish" else "Opening Calculator."
        return {"handled": True, "fast_path": True, "response_text": resp, "action": "launch_calculator", "data": res, "lang": lang}

    if re.search(r'\b(open (?:notepad|editor)|notepad kholo)\b', lower):
        res = launch_application("notepad")
        resp = "Notepad khol diya hai." if lang == "hinglish" else "Opening Notepad."
        return {"handled": True, "fast_path": True, "response_text": resp, "action": "launch_notepad", "data": res, "lang": lang}

    open_app_match = re.search(r'\b(?:open|launch|start|kholo|chalao)\s+([a-zA-Z0-9_\- ]+)\b', lower)
    if open_app_match and not re.search(r'\b(?:website|link|page|url|tab|file|folder|resume|pdf)\b', lower):
        app_target = open_app_match.group(1).replace("kholo", "").replace("chalao", "").strip()
        if app_target in ["spotify", "task manager", "paint", "explorer", "files"]:
            res = launch_application(app_target)
            resp = f"{app_target.title()} khol diya hai." if lang == "hinglish" else f"Opening {app_target.title()}."
            return {"handled": True, "fast_path": True, "response_text": resp, "action": "launch_app", "data": res, "lang": lang}

    # 6. Close Applications
    close_match = re.search(r'\b(?:close|quit|exit|band karo)\s+([a-zA-Z0-9_\- ]+)\b', lower)
    if close_match:
        app_target = close_match.group(1).replace("band karo", "").strip()
        if app_target in ["notepad", "calculator", "calc", "chrome", "vscode", "spotify", "paint", "camera"]:
            res = close_application(app_target)
            resp = f"{app_target.title()} band kar diya." if lang == "hinglish" else f"Closed {app_target.title()}."
            return {"handled": True, "fast_path": True, "response_text": resp, "action": "close_app", "data": res, "lang": lang}

    # 7. File Operations: Resume, Latest PDF, Downloads
    if re.search(r'\b(find (?:my )?resume|where is my resume|resume dhundo|resume dhundho|open my resume)\b', lower):
        resumes = find_resume_files()
        if resumes:
            top_resume = resumes[0]
            open_file_path(top_resume["path"])
            resp = f"Aapka resume {top_resume['name']} mil gaya hai, maine isse open kar diya." if lang == "hinglish" else f"I found your resume, {top_resume['name']}, and opened it for you."
            return {"handled": True, "fast_path": True, "response_text": resp, "action": "find_resume", "data": resumes, "lang": lang}
        else:
            resp = "Maine aapke folders check kiye, lekin resume naam ki koi file nahi mili." if lang == "hinglish" else "I searched your Documents and Downloads, but couldn't find a resume file."
            return {"handled": True, "fast_path": True, "response_text": resp, "action": "find_resume", "lang": lang}

    if re.search(r'\b(open (?:my )?latest pdf|latest pdf kholo|latest document)\b', lower):
        latest = find_latest_file(".pdf")
        if latest:
            open_file_path(latest["path"])
            resp = f"Aapki latest PDF {latest['name']} open kar di hai." if lang == "hinglish" else f"Opening your most recent PDF: {latest['name']}."
            return {"handled": True, "fast_path": True, "response_text": resp, "action": "open_latest_pdf", "data": latest, "lang": lang}
        else:
            resp = "Koi nayi PDF file nahi mili." if lang == "hinglish" else "I could not find any recent PDF files."
            return {"handled": True, "fast_path": True, "response_text": resp, "action": "open_latest_pdf", "lang": lang}

    if re.search(r'\b(open (?:my )?downloads(?: folder)?|downloads kholo)\b', lower):
        res = launch_application("downloads")
        resp = "Downloads folder open kar diya hai." if lang == "hinglish" else "Opening your Downloads folder."
        return {"handled": True, "fast_path": True, "response_text": resp, "action": "open_downloads", "data": res, "lang": lang}

    # 8. Real Web Search & Spoken Summarization
    web_search_match = re.search(r'\b(?:search (?:the )?(?:internet|web) for|google|search for|find(?: the)? latest)\s+([a-zA-Z0-9_\- ]+)\b', lower)
    if web_search_match and not re.search(r'\b(?:file|folder|document|pdf|resume)\b', lower):
        search_query = web_search_match.group(1).strip()
        search_web_in_browser(search_query)
        
        try:
            from browser.engine import BrowserAgent
            browser = BrowserAgent()
            search_results = await browser.search(search_query, limit=3)
            
            if search_results:
                snippets_text = " ".join([f"{r['title']}: {r['snippet']}" for r in search_results if r.get('snippet')])
                snippets_text = re.sub(r'&[a-zA-Z0-9#]+;', ' ', snippets_text)[:400]
                
                summary_prompt = f"Live search results for '{search_query}': {snippets_text}. Summarize the core finding into ONE conversational spoken sentence for Kunal."
                spoken_summary = await ask_voice_llm(summary_prompt, lang=lang)
                resp = f"I searched the web for {search_query}. {spoken_summary}"
                return {"handled": True, "fast_path": False, "response_text": resp, "action": "web_search_summary", "results": search_results, "query": search_query, "lang": lang}
        except Exception as e:
            print("Web search agent error:", e)

        resp = f"Maine browser mein '{search_query}' search kar diya hai." if lang == "hinglish" else f"I have opened the web search for '{search_query}' in your browser."
        return {"handled": True, "fast_path": True, "response_text": resp, "action": "web_search", "query": search_query, "lang": lang}

    # 9. Screenshots
    if re.search(r'\b(take (?:a )?screenshot|capture screen|screen capture|screenshot lo|screenshot le lo)\b', lower):
        res = capture_desktop_screenshot()
        if res.get("status") == "success":
            resp = "Desktop screenshot capture ho gaya hai." if lang == "hinglish" else "Desktop screenshot captured successfully."
        else:
            resp = "Screenshot capture mein dikkat aayi." if lang == "hinglish" else "Failed to capture desktop screenshot."
        return {"handled": True, "fast_path": True, "response_text": resp, "action": "screenshot", "data": res, "lang": lang}

    # 10. Instant Battery & System Telemetry (<0.6ms via Win32 C API)
    if re.search(r'\b(battery|charge|charging|battery kitni hai|battery status)\b', lower):
        metrics = get_system_metrics()
        bp = metrics["metrics"].get("battery_percent", 90)
        resp = f"Aapki battery {bp}% hai." if lang == "hinglish" else f"Battery is currently at {bp}%."
        return {"handled": True, "fast_path": True, "response_text": resp, "action": "battery_status", "data": metrics, "lang": lang}

    if re.search(r'\b(cpu usage|ram usage|system info|system status|performance|pc ka haal)\b', lower):
        metrics = get_system_metrics()
        m = metrics["metrics"]
        resp = (
            f"RAM {m['ram_usage_percent']}% use ho rahi hai ({m['free_ram_mb']} MB free hai)."
            if lang == "hinglish" else
            f"RAM is at {m['ram_usage_percent']}% utilization with {m['free_ram_mb']} MB free."
        )
        return {"handled": True, "fast_path": True, "response_text": resp, "action": "system_status", "data": metrics, "lang": lang}

    # 11. Time & Date (<1ms)
    if re.search(r'\b(what time is it|current time|kya samay hua|time batao|kitne baje hain)\b', lower):
        now = datetime.datetime.now()
        time_str = now.strftime("%I:%M %p")
        resp = f"Abhi samay {time_str} hua hai." if lang == "hinglish" else f"It is currently {time_str}."
        return {"handled": True, "fast_path": True, "response_text": resp, "action": "time", "data": {"time": time_str}, "lang": lang}

    if re.search(r'\b(today\'?s? date|what is today|aaj ki date|aaj kaun sa din)\b', lower):
        now = datetime.datetime.now()
        date_str = now.strftime("%A, %B %d, %Y")
        resp = f"Aaj {date_str} hai." if lang == "hinglish" else f"Today is {date_str}."
        return {"handled": True, "fast_path": True, "response_text": resp, "action": "date", "data": {"date": date_str}, "lang": lang}

    # 12. Fast Conversational LLM Fallback (max 30 tokens, 3.5s timeout)
    llm_resp = await ask_voice_llm(clean, lang=lang)
    return {
        "handled": True,
        "fast_path": False,
        "response_text": llm_resp,
        "action": "conversational_ai",
        "lang": lang
    }
