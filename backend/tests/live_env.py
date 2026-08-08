import os
from pathlib import Path

# Load env vars from the standard locations, closest file wins
def load_env() -> None:
    backend_dir = Path(__file__).resolve().parent.parent
    candidates = [
        backend_dir / ".env",
        backend_dir / ".env.local",
        # Next.js convention
        backend_dir.parent / ".env.local",
    ]
    for env_path in candidates:
        if not env_path.exists():
            continue
        for line in env_path.read_text().splitlines():
            m_line = line.strip()
            if not m_line or m_line.startswith("#"):
                continue
            if "=" in m_line:
                key, _, value = m_line.partition("=")
                key = key.strip()
                value = value.strip()
                if key and value:
                    os.environ.setdefault(key, value)


load_env()

API_KEY = os.environ.get("LASTFM_API_KEY", "")
