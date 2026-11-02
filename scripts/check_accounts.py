"""Check that the API keys in your .env file work. Safe to run: it never prints a key.
 
Run from the project folder (virtual environment active):
    python scripts/check_accounts.py
 
Each service prints one line: OK, SKIP (key not filled in) or FAIL (with a hint).
Only Python's standard library is used, so no extra install is needed.
"""
from __future__ import annotations
 
import base64
import json
import os
import urllib.error
import urllib.request
from pathlib import Path
 
ROOT = Path(__file__).resolve().parents[1]
 
 
def load_env(path: Path) -> dict[str, str]:
    """Read KEY=value lines from .env; real environment variables override the file."""
    env: dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            env[key.strip()] = value.split("#", 1)[0].strip().strip('"').strip("'")
    for key in list(env):
        env[key] = os.environ.get(key, env[key])
    return env
 
 
def is_set(value: str | None) -> bool:
    return bool(value) and not value.lower().startswith("your-")
 
 
def http_get(url: str, headers: dict[str, str]) -> tuple[int | None, bytes]:
    req = urllib.request.Request(url, headers={"User-Agent": "scm-check/1.0", **headers})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as err:
        return err.code, b""
    except Exception as err:  # no internet, DNS problem, firewall...
        return None, str(err).encode()
 
 
def report(name: str, status: int | None, ok_codes: tuple[int, ...] = (200,)) -> None:
    if status in ok_codes:
        print(f"[ OK   ] {name}")
    elif status in (401, 403):
        print(f"[ FAIL ] {name}: the service rejected the key (HTTP {status}). Re-copy the key, with no spaces or quotes.")
    elif status is None:
        print(f"[ FAIL ] {name}: could not reach the service. Check your internet connection or firewall.")
    else:
        print(f"[ FAIL ] {name}: unexpected answer (HTTP {status}).")
 
 
def main() -> None:
    env = load_env(ROOT / ".env")
    if not (ROOT / ".env").exists():
        print("No .env file found. Copy .env.example to .env and fill in your keys first.")
        return
 
    key = env.get("GROQ_API_KEY")
    if is_set(key):
        status, _ = http_get("https://api.groq.com/openai/v1/models", {"Authorization": f"Bearer {key}"})
        report("Groq", status)
    else:
        print("[ SKIP ] Groq (GROQ_API_KEY not filled in)")
 
    key = env.get("GOOGLE_API_KEY")
    if is_set(key):
        status, _ = http_get("https://generativelanguage.googleapis.com/v1beta/models", {"x-goog-api-key": key})
        report("Google AI Studio (Gemini)", status)
    else:
        print("[ SKIP ] Google AI Studio (GOOGLE_API_KEY not filled in)")
 
    key = env.get("HF_TOKEN")
    if is_set(key):
        status, body = http_get("https://huggingface.co/api/whoami-v2", {"Authorization": f"Bearer {key}"})
        report("Hugging Face", status)
        if status == 200:
            try:
                print(f"         logged in as: {json.loads(body).get('name')}")
            except ValueError:
                pass
    else:
        print("[ SKIP ] Hugging Face (HF_TOKEN not filled in)")
 
    pub, sec = env.get("LANGFUSE_PUBLIC_KEY"), env.get("LANGFUSE_SECRET_KEY")
    host = env.get("LANGFUSE_HOST", "https://cloud.langfuse.com").rstrip("/")
    if is_set(pub) and is_set(sec):
        token = base64.b64encode(f"{pub}:{sec}".encode()).decode()
        status, _ = http_get(f"{host}/api/public/projects", {"Authorization": f"Basic {token}"})
        report("Langfuse", status)
    else:
        print("[ SKIP ] Langfuse (LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY not filled in)")
 
 
if __name__ == "__main__":
    main()
    