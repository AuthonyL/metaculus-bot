"""
Research step backed by Claude's server-side web search (direct Anthropic API only).

Used when bot_config picks the "anthropic" route and no AskNews key is set. One streamed
request: Claude searches the web up to MAX_SEARCHES times and writes the research rundown
the forecaster prompt expects. Costs: model tokens + $10 per 1,000 searches.
"""
from __future__ import annotations

import asyncio
import os

import anthropic

RESEARCH_MODEL = os.getenv("RESEARCH_MODEL", "claude-sonnet-5-5")
MAX_SEARCHES = int(os.getenv("RESEARCH_MAX_SEARCHES", "5"))

_client: anthropic.AsyncAnthropic | None = None


def _get_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic(timeout=300.0, max_retries=2)
    return _client


async def research_with_web_search(prompt: str) -> str:
    """Run the research prompt with web search enabled; return the text Claude wrote."""
    client = _get_client()
    async with client.beta.messages.stream(
        model=RESEARCH_MODEL,
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",  # route a safety refusal to a fallback model instead of returning nothing
        system=(
            "You are a research assistant to a superforecaster. Search the web for the latest "
            "relevant facts, prefer primary sources and recent news, and report what you found "
            "with dates. Do not give a probability yourself."
        ),
        tools=[{"type": "web_search_20260209", "name": "web_search", "max_uses": MAX_SEARCHES}],
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        message = await stream.get_final_message()

    if message.stop_reason == "refusal":
        detail = message.stop_details.explanation if message.stop_details else ""
        return f"(research unavailable: request declined by safety classifier {detail})"

    text = "\n".join(block.text for block in message.content if block.type == "text").strip()
    searches = sum(1 for block in message.content if block.type == "server_tool_use")
    return f"{text}\n\n[web searches used: {searches}]" if text else "(no research text returned)"


if __name__ == "__main__":
    # quick manual check: python claude_research.py "Will X happen by 2027?"
    import sys

    print(asyncio.run(research_with_web_search(sys.argv[1] if len(sys.argv) > 1 else "Who is the current UN Secretary-General?")))
