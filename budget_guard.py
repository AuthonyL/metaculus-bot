"""
Hard spend cap for the OpenRouter key, checked before every run.

litellm's price table does not cover OpenRouter model ids reliably (rc_trader saw $0.00 costs),
so instead of trusting local cost estimates we ask OpenRouter how much the key has spent and
refuse to start a run once that passes OPENROUTER_SPEND_CAP_USD (default 25).

    .venv/bin/python budget_guard.py      # prints usage / limit and exits 0 (ok) or 2 (cap hit)
"""
from __future__ import annotations

import os
import sys

import requests

from bot_helpers import _is_real_env

def cap_usd() -> float:
    # read at call time so a .env loaded after import (main.py, smoke_test.py) is honoured
    return float(os.getenv("OPENROUTER_SPEND_CAP_USD", "25"))


def openrouter_usage() -> dict | None:
    """{'usage': float, 'limit': float|None, 'limit_remaining': float|None} or None when no key."""
    if not _is_real_env("OPENROUTER_API_KEY"):
        return None
    r = requests.get(
        "https://openrouter.ai/api/v1/auth/key",
        headers={"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}"},
        timeout=20,
    )
    r.raise_for_status()
    d = r.json()["data"]
    return {"usage": float(d.get("usage") or 0), "limit": d.get("limit"), "limit_remaining": d.get("limit_remaining")}


def check_budget(strict: bool = True) -> dict | None:
    """Print usage and stop the process when the cap is reached (strict) — call at startup."""
    try:
        u = openrouter_usage()
    except Exception as e:  # network/API trouble: warn, don't block a run on it
        print(f"⚠️  budget_guard: could not read OpenRouter usage ({type(e).__name__}: {str(e)[:80]})")
        return None
    if u is None:
        return None
    cap = cap_usd()
    print(f"💵  OpenRouter spent ${u['usage']:.2f} / cap ${cap:.2f}"
          + (f" (key limit remaining ${u['limit_remaining']:.2f})" if u.get("limit_remaining") is not None else ""))
    if u["usage"] >= cap:
        print(f"⛔  Spend cap reached (${u['usage']:.2f} ≥ ${cap:.2f}). Raise OPENROUTER_SPEND_CAP_USD to continue.")
        if strict:
            sys.exit(2)
    return u


if __name__ == "__main__":
    import dotenv

    dotenv.load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
    check_budget(strict=True)
