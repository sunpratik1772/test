"""Quick Gemini API key probe — tests all 4 keys against gemini-2.0-flash."""
import json
import ssl
import urllib.request
import urllib.error

# Use certifi bundle to fix macOS SSL cert verification
try:
    import certifi
    _SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _SSL_CTX = ssl.create_default_context()

import os

# Load key from environment — never hardcode API keys in source
KEYS = [
    ("KEY_1", os.environ.get("GOOGLE_API_KEY", "")),
]

MODEL = "gemini-2.0-flash"


def probe(name: str, key: str) -> tuple[bool, str]:
    url = (
        f"https://generativelanguage.googleapis.com/v1beta"
        f"/models/{MODEL}:generateContent?key={key}"
    )
    payload = json.dumps({
        "contents": [{"parts": [{"text": "Reply with exactly: GEMINI_OK"}]}]
    }).encode()
    req = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=10, context=_SSL_CTX) as resp:
            body = json.loads(resp.read())
            text = body["candidates"][0]["content"]["parts"][0]["text"].strip()
            return True, text
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        return False, f"HTTP {e.code}: {body[:200]}"
    except Exception as e:
        return False, str(e)


if __name__ == "__main__":
    any_ok = False
    for name, key in KEYS:
        ok, msg = probe(name, key)
        status = "✓ OK" if ok else "✗ FAIL"
        print(f"  {name}: {status}  →  {msg[:100]}")
        if ok:
            any_ok = True

    print()
    print("RESULT:", "At least one key works — ready to build." if any_ok else "ALL KEYS FAILED — need new key.")
