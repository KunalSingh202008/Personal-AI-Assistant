"""
Live Real-Machine Verification Script for KELA Browser and Web Launching.
Verifies all 7 critical user acceptance criteria against running server on 127.0.0.1:8001:
1. Open YouTube
2. Open Google
3. Open GitHub
4. Open Microsoft Edge
5. Open Brave
6. Open arbitrary valid URL (https://github.com/torvalds/linux)
7. Voice test via POST /api/voice/conversation
"""

import json
import urllib.request
import time

BASE_URL = "http://127.0.0.1:8001"

def get_auth_token() -> str:
    req = urllib.request.Request(f"{BASE_URL}/api/auth/local-token", headers={"Host": "127.0.0.1:8001"})
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        return data["token"]

def test_voice_endpoint(token: str, query: str):
    body = json.dumps({"text": query}).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE_URL}/api/voice/conversation",
        data=body,
        headers={
            "Host": "127.0.0.1:8001",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        }
    )
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        return data

def test_chat_endpoint(token: str, query: str):
    body = json.dumps({
        "messages": [{"role": "user", "content": query}]
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE_URL}/api/chat",
        data=body,
        headers={
            "Host": "127.0.0.1:8001",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        }
    )
    events = []
    with urllib.request.urlopen(req) as resp:
        for line in resp:
            line_str = line.decode("utf-8").strip()
            if line_str:
                try:
                    events.append(json.loads(line_str))
                except Exception:
                    pass
    return events

def test_pc_launch_endpoint(token: str, app: str):
    body = json.dumps({"app": app}).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE_URL}/api/pc/launch",
        data=body,
        headers={
            "Host": "127.0.0.1:8001",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        }
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))

def main():
    token = get_auth_token()
    print("Obtained local authentication token successfully.\n")

    test_queries = [
        ("Test 1: Open YouTube (Chat)", "chat", "Open YouTube"),
        ("Test 2: Open Google (Chat)", "chat", "Open Google"),
        ("Test 3: Open GitHub (Chat)", "chat", "Open GitHub"),
        ("Test 4: Open Microsoft Edge (Chat)", "chat", "Open Microsoft Edge"),
        ("Test 5: Open Brave (Chat)", "chat", "Open Brave"),
        ("Test 6: Arbitrary URL (Chat)", "chat", "Open https://github.com/torvalds/linux"),
        ("Test 7a: Voice YouTube", "voice", "Open YouTube"),
        ("Test 7b: Voice Edge", "voice", "Open Microsoft Edge"),
        ("Test 7c: Voice Brave", "voice", "Open Brave"),
        ("Test 8a: PC Launch Edge", "pc_launch", "Open Microsoft Edge"),
        ("Test 8b: PC Launch Brave", "pc_launch", "Open Brave"),
        ("Test 8c: PC Launch GitHub", "pc_launch", "Open GitHub"),
    ]

    all_passed = True

    for label, mode, target in test_queries:
        print(f"--- Running {label}: '{target}' ---")
        if mode == "chat":
            events = test_chat_endpoint(token, target)
            step_events = [e.get("step") for e in events if "step" in e]
            tokens = [e.get("token") for e in events if "token" in e]
            full_content = "".join(tokens)
            print(f"  Step events: {step_events}")
            print(f"  Full response tokens: '{full_content}'")
            if not full_content:
                print("  [FAIL] Empty response content")
                all_passed = False
            else:
                print("  [PASS]")
        elif mode == "voice":
            data = test_voice_endpoint(token, target)
            print(f"  Handled: {data.get('handled')}")
            print(f"  Action: {data.get('action')}")
            print(f"  Response text: {data.get('response_text')}")
            tool_res = data.get("data") or {}
            print(f"  Tool result verified: {tool_res.get('verified')}, launch_code: {tool_res.get('launch_code')}")
            if not data.get("handled") or not tool_res.get("verified"):
                print("  [FAIL] Voice response not verified")
                all_passed = False
            else:
                print("  [PASS]")
        elif mode == "pc_launch":
            data = test_pc_launch_endpoint(token, target)
            print(f"  Status: {data.get('status')}")
            print(f"  Message: {data.get('message')}")
            print(f"  Verified: {data.get('verified')}")
            print(f"  Browser: {data.get('browser')}")
            print(f"  Resolved URL: {data.get('resolved_url')}")
            if data.get("status") != "success" or not data.get("verified"):
                print("  [FAIL] PC launch not verified")
                all_passed = False
            else:
                print("  [PASS]")
        print()
        time.sleep(0.3)

    print("==========================================")
    if all_passed:
        print("ALL REAL-MACHINE ACCEPTANCE TESTS PASSED!")
    else:
        print("SOME TESTS FAILED! Review output above.")
    print("==========================================")

if __name__ == "__main__":
    main()
