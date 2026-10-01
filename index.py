"""Vercel entrypoint: Vercel looks for a FastAPI `app` in index.py at the project root."""
from src.api.app import app  # noqa: F401
