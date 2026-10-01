"""Deploy settings read from environment variables. A local .env in 03-solution/ is loaded if present."""
from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # python-dotenv is optional; hosts like Render set env vars directly
    load_dotenv = None

ROOT = Path(__file__).resolve().parents[1]
if load_dotenv:
    load_dotenv(ROOT / ".env")


def _csv(name: str, default: str) -> list[str]:
    return [v.strip().rstrip("/") for v in os.getenv(name, default).split(",") if v.strip()]


# Frontend origins allowed to call the API (comma-separated), e.g. https://my-app.vercel.app
CORS_ORIGINS = _csv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
# Optional regex for extra origins, e.g. Vercel preview URLs: https://my-app-.*\.vercel\.app
CORS_ORIGIN_REGEX = os.getenv("CORS_ORIGIN_REGEX") or None
# SQLite audit log path; empty falls back to audit_db in config/engine.yaml.
# On Vercel only /tmp is writable (and it is wiped when the instance is recycled).
AUDIT_DB = os.getenv("AUDIT_DB") or ("/tmp/audit.sqlite" if os.getenv("VERCEL") else None)
