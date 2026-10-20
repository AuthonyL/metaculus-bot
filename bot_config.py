"""
Model selection for the bot. Everything is Claude; which route we take depends on
which key is present:

  ANTHROPIC_API_KEY   -> direct Anthropic API (litellm "anthropic/..." names),
                         research via Claude's own web_search tool (claude_research.py)
  OPENROUTER_API_KEY  -> OpenRouter (the key Metaculus hands out with the free credits),
                         research via OpenRouter's ":online" web plugin
  neither             -> return None so forecasting-tools picks its own defaults

Override any role with FORECASTER_MODEL / PARSER_MODEL / SUMMARIZER_MODEL / RESEARCHER_MODEL.
Model ids differ between the two routes (dashes vs dots), so the table below keeps both.
"""
from __future__ import annotations

import os

from forecasting_tools import GeneralLlm

from bot_helpers import _is_real_env  # treats REPLACE_ME-style placeholders as unset

# role -> (direct Anthropic id, OpenRouter slug)
_CLAUDE = {
    "opus": ("claude-opus-5-5", "claude-opus-5.5"),
    "sonnet": ("claude-sonnet-5-5", "claude-sonnet-5.5"),
    "haiku": ("claude-haiku-5-5", "claude-haiku-5.5"),
}

# OpenRouter route. This account gets HTTP 403 from OpenAI/Anthropic/Google (account-region
# enforcement), so the defaults are the strongest providers that do serve it (probed 2026-10-18).
# Research uses OpenRouter's ":online" web plugin, which works on any model.
_OR_FORECASTER = "openrouter/x-ai/grok-4.7"
_OR_CHEAP = "openrouter/deepseek/deepseek-v4.1-flash"
# Benchmark 2026-10-18 (15 Polymarket questions, market price as reference, ceiling 31.3):
# Grok+Grok:online research 26.3 > Grok+flash:online 14.6 > Kimi+flash 13.0 > DeepSeek+flash 11.2 > no research ~7.7.
_OR_RESEARCHER = "openrouter/x-ai/grok-4.7:online"
HIGH_REASONING = {"extra_body": {"reasoning": {"effort": "high"}}}  # OpenRouter's native switch

# Marker understood by the bot's run_research override (see main.py).
CLAUDE_WEB_SEARCH = "claude-web-search"


def _route() -> str | None:
    if _is_real_env("ANTHROPIC_API_KEY"):
        return "anthropic"
    if _is_real_env("OPENROUTER_API_KEY"):
        return "openrouter"
    return None


def _model(tier: str, route: str) -> str:
    direct, slug = _CLAUDE[tier]
    return f"anthropic/{direct}" if route == "anthropic" else f"openrouter/anthropic/{slug}"


def _has_asknews() -> bool:
    return _is_real_env("ASKNEWS_API_KEY") or (_is_real_env("ASKNEWS_CLIENT_ID") and _is_real_env("ASKNEWS_SECRET"))


def build_llms() -> dict[str, str | GeneralLlm] | None:
    route = _route()
    if route is None:
        return None

    # No temperature anywhere: Claude 5.5 rejects non-default sampling params, and the
    # multiple predictions per research report get their diversity from default sampling.
    if route == "anthropic":
        forecaster = GeneralLlm(model=os.getenv("FORECASTER_MODEL") or _model("opus", route), timeout=240, allowed_tries=2)
        parser = GeneralLlm(model=os.getenv("PARSER_MODEL") or _model("haiku", route), timeout=90, allowed_tries=3)
        summarizer = GeneralLlm(model=os.getenv("SUMMARIZER_MODEL") or _model("haiku", route), timeout=120, allowed_tries=2)
    else:
        # 900 s: Grok 4.7 at high effort regularly needs 5+ min; at 300 s whole runs timed out and
        # the generations were billed anyway (2026-10-20, question 46069).
        forecaster = GeneralLlm(
            model=os.getenv("FORECASTER_MODEL") or _OR_FORECASTER,
            timeout=int(os.getenv("FORECASTER_TIMEOUT", "900")),
            allowed_tries=2,
            **HIGH_REASONING,
        )
        parser = GeneralLlm(model=os.getenv("PARSER_MODEL") or _OR_CHEAP, timeout=90, allowed_tries=3)
        summarizer = GeneralLlm(model=os.getenv("SUMMARIZER_MODEL") or _OR_CHEAP, timeout=120, allowed_tries=2)

    researcher: str | GeneralLlm
    if os.getenv("RESEARCHER_MODEL"):
        researcher = os.getenv("RESEARCHER_MODEL", "")
    elif _has_asknews():
        researcher = "asknews/news-summaries"
    elif route == "anthropic":
        researcher = CLAUDE_WEB_SEARCH
    else:
        researcher = GeneralLlm(model=_OR_RESEARCHER, timeout=240, allowed_tries=2)

    return {"default": forecaster, "parser": parser, "summarizer": summarizer, "researcher": researcher}


def describe_llms(llms: dict | None) -> str:
    if llms is None:
        return "forecasting-tools defaults (no ANTHROPIC/OPENROUTER key found)"
    return ", ".join(f"{k}={GeneralLlm.to_model_name(v) if isinstance(v, GeneralLlm) else v}" for k, v in llms.items())
