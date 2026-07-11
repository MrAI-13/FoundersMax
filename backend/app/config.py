"""Environment configuration.

Loads `.env` from either the backend/ directory or the repo root (whichever
exists), so `uvicorn` works the same whether it's launched from the repo
root or from backend/. All inference for the agent goes through OpenRouter
(one OpenAI-compatible endpoint that can proxy Claude, Llama, GPT-OSS, etc.)
so swapping models later is an env var change, not a code change. Voice
(OpenAI Realtime API) is unrelated to this and still talks to OpenAI
directly — see voice.py.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

_BACKEND_DIR = Path(__file__).resolve().parent.parent
_REPO_ROOT = _BACKEND_DIR.parent

for _candidate in (_BACKEND_DIR / ".env", _REPO_ROOT / ".env"):
    if _candidate.exists():
        load_dotenv(_candidate, override=False)

OPENROUTER_API_KEY = os.environ.get("OPEN_ROUTER_API_KEY", "").strip()
OPENROUTER_BASE_URL = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").strip()
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "nvidia/nemotron-nano-9b-v2:free").strip()

# OpenRouter uses these to attribute traffic on https://openrouter.ai/rankings; optional but free.
OPENROUTER_SITE_URL = os.environ.get("OPENROUTER_SITE_URL", "http://localhost:5173").strip()
OPENROUTER_APP_NAME = os.environ.get("OPENROUTER_APP_NAME", "FoundersMax Customer Support").strip()

OPENAI_API_KEY = os.environ.get("OPEN_AI_API_KEY", "").strip()
OPENAI_REALTIME_MODEL = os.environ.get("OPENAI_REALTIME_MODEL", "gpt-realtime-2.1").strip()
# "marin" and "cedar" are OpenAI's recommended highest-quality Realtime voices.
OPENAI_VOICE = os.environ.get("OPENAI_VOICE", "marin").strip()


def require_openrouter_api_key() -> str:
    if not OPENROUTER_API_KEY:
        raise RuntimeError(
            "OPEN_ROUTER_API_KEY is not set. Add it to backend/.env or the repo-root .env "
            "(see backend/.env.example)."
        )
    return OPENROUTER_API_KEY


def require_openai_api_key() -> str:
    if not OPENAI_API_KEY:
        raise RuntimeError(
            "OPEN_AI_API_KEY is not set. Add it to backend/.env or the repo-root .env "
            "(see backend/.env.example) to use the voice pipeline."
        )
    return OPENAI_API_KEY
