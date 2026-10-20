"""
Per-question attempt memory, so a question that keeps failing is not retried forever.

Why: on 2026-10-20 question 46069 timed out on every Grok call; because the bot only skips
questions it has *successfully* forecast, each 15-minute run re-ran the research and all three
forecasts again — 8 attempts, ~$7, zero forecasts posted. Now every question gets at most
MAX_ATTEMPTS_PER_QUESTION tries (default 2) within ATTEMPT_TTL_DAYS.

State is a tiny JSON file in state/attempts.json. On GitHub Actions the workflow restores and
saves that directory through actions/cache, so the memory survives between runs. Entries expire
after a few days, which is longer than any question stays open (3 h).
"""
from __future__ import annotations

import json
import os
import time
from typing import Sequence

STATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state")
STATE_FILE = os.path.join(STATE_DIR, "attempts.json")


def max_attempts() -> int:
    return int(os.getenv("MAX_ATTEMPTS_PER_QUESTION", "2"))


def _ttl_seconds() -> float:
    return float(os.getenv("ATTEMPT_TTL_DAYS", "3")) * 86400


def load_attempts() -> dict[str, dict]:
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    now = time.time()
    return {k: v for k, v in data.items() if isinstance(v, dict) and now - v.get("t", 0) < _ttl_seconds()}


def save_attempts(data: dict[str, dict]) -> None:
    os.makedirs(STATE_DIR, exist_ok=True)
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, sort_keys=True)
    os.replace(tmp, STATE_FILE)


def _key(question) -> str:
    return str(getattr(question, "id_of_post", None) or getattr(question, "page_url", None) or id(question))


def filter_by_attempts(questions: Sequence) -> tuple[list, list]:
    """Split questions into (to_forecast, skipped) and record one attempt for each kept question.

    The attempt is recorded *before* forecasting, so a crash mid-run still counts.
    """
    data = load_attempts()
    limit = max_attempts()
    now = time.time()
    keep, skipped = [], []
    for q in questions:
        k = _key(q)
        n = int(data.get(k, {}).get("n", 0))
        if n >= limit:
            skipped.append(q)
            continue
        data[k] = {"n": n + 1, "t": now}
        keep.append(q)
    save_attempts(data)
    return keep, skipped
