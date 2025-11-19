import re
import json
import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
}

def extract_json_from_script(script_text: str) -> dict:
    """Extracts the first JSON object found in script text using brace matching."""
    start = script_text.find("{")
    if start == -1:
        return None

    depth = 0
    for i in range(start, len(script_text)):
        if script_text[i] == "{":
            depth += 1
        elif script_text[i] == "}":
            depth -= 1
            if depth == 0:
                json_text = script_text[start:i+1]
                try:
                    return json.loads(json_text)
                except:
                    return None
    return None

def fetch_state(url: str) -> dict:
    session = requests.Session()
    session.headers.update(HEADERS)

    resp = session.get(url, timeout=12)
    if resp.status_code != 200:
        raise Exception(f"HTTP Error {resp.status_code}")

    soup = BeautifulSoup(resp.text, "lxml")
    scripts = [s.string for s in soup.find_all("script") if s.string]

    # Search patterns to detect the correct script block
    state_keys = [
        "window.__PRELOADED_STATE__",
        "window.__INITIAL_STATE__",
        "__RMLISTING_STATE__",
        '"propertyData":',
        '"pageData":'
    ]

    for script in scripts:
        if any(key in script for key in state_keys):
            data = extract_json_from_script(script)
            if data:
                return {
                    "url": url,
                    "status": "fetched_state",
                    "state": data
                }

    raise Exception("State JSON not found on page.")

# TEST
url = "https://www.rightmove.co.uk/properties/162406493#/?channel=RES_BUY"
data = fetch_state(url)
print("✅ Status:", data["status"])
print("🔑 Top level keys:", list(data["state"].keys())[:10])

