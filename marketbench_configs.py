"""
Phase 2 (working version): compare bot configs against *prediction-market prices*.

The Metaculus API no longer returns community predictions or resolutions to our account tier,
so the CP benchmark and the resolved-question pastcast are both impossible. Polymarket's public
Gamma API does expose live prices, so we use money-backed market odds as the reference instead:
score = expected Metaculus Baseline score if the market price were the true probability.
Open markets only (no outcome leakage); research is allowed, but the prompts tell the models to
ignore prediction-market odds so the reference does not leak into the forecast.

    .venv/bin/python marketbench_configs.py --questions 15
    .venv/bin/python marketbench_configs.py --questions 2 --only GROK      # preflight
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import math
import os
import re
import statistics as st
import time
from datetime import datetime, timedelta, timezone

import dotenv

dotenv.load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

from bot_helpers import silence_noisy_dependencies  # noqa: E402

silence_noisy_dependencies()

import requests  # noqa: E402
from forecasting_tools import BinaryQuestion, GeneralLlm, MetaculusQuestion, clean_indents  # noqa: E402

from budget_guard import check_budget, openrouter_usage  # noqa: E402
from main import FallTemplateBot2026  # noqa: E402

OR = "openrouter/"
HIGH = {"extra_body": {"reasoning": {"effort": "high"}}}
FLASH = OR + "deepseek/deepseek-v4.1-flash"
FLASH_ONLINE = FLASH + ":online"
NO_MARKETS = "Do NOT look up or report prediction-market odds (Polymarket, Kalshi, Manifold, Metaculus); use news and primary sources only."
ANSWER_NOW = ("You have no browsing tools in this step: do not describe what you would research, write the full analysis now "
              "from the material above and your own knowledge, and end with the final line 'Probability: ZZ%'.")


def llm(model: str, **kw) -> GeneralLlm:
    return GeneralLlm(model=model, timeout=300, allowed_tries=2, **kw)


GROK = OR + "x-ai/grok-4.7"
KIMI = OR + "moonshotai/kimi-k3"
CONFIGS: dict[str, tuple[GeneralLlm, GeneralLlm | str]] = {
    # round 1 (2026-10-18): no_research 23.2 > kimi+flash 15.1 > grok+flash 11.2 > deepseek+flash 5.3 (ceiling 30.2)
    "GROK47_high__flash_research": (llm(GROK, **HIGH), llm(FLASH_ONLINE)),
    "KIMIK3_high__flash_research": (llm(KIMI, **HIGH), llm(FLASH_ONLINE)),
    "DEEPSEEKv4pro_high__flash_research": (llm(OR + "deepseek/deepseek-v4-pro", **HIGH), llm(FLASH_ONLINE)),
    "GROK47_high__no_research": (llm(GROK, **HIGH), "no_research"),
    # round 2: is it the research *module* that hurt, or research per se?
    "GROK47_high__grok_online_research": (llm(GROK, **HIGH), llm(GROK + ":online")),   # strong researcher
    "GROK47online_high__self_search": (llm(GROK + ":online", **HIGH), "no_research"),  # forecaster browses itself
    "KIMIK3_high__no_research": (llm(KIMI, **HIGH), "no_research"),                   # research effect on Kimi
}

SPORTS = re.compile(r"\b(win on 20\d\d|vs\.?|spread:|o/u|over/under|match|game|cup|league|open:|bo3|bo5|nba|nfl|mlb|nhl|ufc|f1|grand prix|tennis|football|soccer|basketball|baseball|hockey|cricket|counter-strike|dota|valorant|esports)\b", re.I)


class MarketBot(FallTemplateBot2026):
    """Template bot whose prompts exclude prediction-market odds (the benchmark reference)."""

    @staticmethod
    def _get_research_prompt(question: MetaculusQuestion, researcher) -> str:
        return FallTemplateBot2026._get_research_prompt(question, researcher) + "\n" + NO_MARKETS

    async def _run_forecast_on_binary(self, question: BinaryQuestion, research: str):
        question = question.model_copy(update={"fine_print": (question.fine_print or "") + "\n\n" + NO_MARKETS + "\n" + ANSWER_NOW})
        return await super()._run_forecast_on_binary(question, research)


def make_bot(name: str, forecaster: GeneralLlm, researcher: GeneralLlm | str) -> MarketBot:
    # The template serialises questions (semaphore of 1); 4 in flight keeps a 15-question run under ~15 min per config.
    cls = type(f"Bot_{name}", (MarketBot,), {"_max_concurrent_questions": 4, "_concurrency_limiter": asyncio.Semaphore(4)})
    return cls(
        research_reports_per_question=1,
        predictions_per_research_report=3,
        publish_reports_to_metaculus=False,
        folder_to_save_reports_to=None,
        skip_previously_forecasted_questions=False,
        llms={"default": forecaster, "researcher": researcher, "parser": llm(FLASH), "summarizer": llm(FLASH)},
    )


SPORT_TAGS = {"sports", "games", "soccer", "cfb", "nfl", "epl", "premier-league", "tennis", "nba", "mlb", "nhl",
              "ufc", "mma", "esports", "cricket", "golf", "f1", "boxing", "cbb", "ncaa", "la-liga", "serie-a", "bundesliga",
              "ligue-1", "champions-league", "europa-league", "mls", "wnba", "nascar", "rugby", "investec-champions-cup"}


def _loads(v):
    import json as _json
    return _json.loads(v) if isinstance(v, str) else v


def fetch_markets(n: int, min_days: int = 5, max_days: int = 180) -> list[tuple[BinaryQuestion, float]]:
    """One liquid Yes/No market per non-sports Polymarket *event*, closing in [min_days, max_days].
    Walks the events feed by 24h volume (sports dominate it, so several pages); returns (question, market_p)."""
    now = datetime.now(timezone.utc)
    out: list[tuple[BinaryQuestion, float]] = []
    for offset in range(0, 500, 100):
        r = requests.get("https://gamma-api.polymarket.com/events",
                         params={"active": "true", "closed": "false", "limit": 100, "offset": offset,
                                 "order": "volume24hr", "ascending": "false"}, timeout=30)
        r.raise_for_status()
        events = r.json()
        for e in events:
            try:
                tags = {t.get("slug") for t in (e.get("tags") or [])}
                if e.get("sport") or (tags & SPORT_TAGS) or e.get("gameId"):
                    continue
                best = None
                for m in e.get("markets") or []:
                    if _loads(m.get("outcomes")) != ["Yes", "No"] or m.get("gameStartTime") or SPORTS.search(m.get("question", "")):
                        continue
                    p_yes = float(_loads(m.get("outcomePrices"))[0])
                    liq = float(m.get("liquidityNum") or 0)
                    end = datetime.fromisoformat(m["endDate"].replace("Z", "+00:00"))
                    if not 0.05 <= p_yes <= 0.95 or liq < 5_000:
                        continue
                    if not (now + timedelta(days=min_days) <= end <= now + timedelta(days=max_days)):
                        continue
                    if best is None or liq > best[2]:
                        best = (m, p_yes, liq, end)
                if best is None:
                    continue
                m, p_yes, _, end = best
                created = datetime.fromisoformat(m["createdAt"].replace("Z", "+00:00")) if m.get("createdAt") else now - timedelta(days=30)
                q = BinaryQuestion(
                    question_text=m["question"],
                    background_info=e.get("description") or "",
                    resolution_criteria=m.get("description") or "",
                    fine_print="",
                    page_url=f"https://polymarket.com/event/{e.get('slug', e.get('id'))}",
                    id_of_post=0, id_of_question=0,
                    close_time=end, scheduled_resolution_time=end, open_time=created, published_time=created,
                )
                out.append((q, p_yes))
            except Exception:
                continue
            if len(out) >= n:
                return out
        if len(events) < 100:
            break
    return out


def baseline(p: float, yes: bool) -> float:
    p = min(0.99, max(0.01, p))
    return 100 * math.log2((p if yes else 1 - p) / 0.5)


def expected_baseline(p: float, m: float) -> float:
    return m * baseline(p, True) + (1 - m) * baseline(p, False)


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--questions", type=int, default=15)
    ap.add_argument("--only", nargs="*")
    args = ap.parse_args()

    check_budget(strict=True)
    before = openrouter_usage()
    markets = fetch_markets(args.questions)
    if not markets:
        raise SystemExit("no markets matched the filter")
    print(f"markets: {len(markets)}")
    for q, m in markets:
        print(f"  - {q.question_text[:78]:78s} market={m:.2f} close={str(q.close_time)[:10]}")
    print()

    chosen = {k: v for k, v in CONFIGS.items() if not args.only or any(k.startswith(p) for p in args.only)}
    questions = [q for q, _ in markets]
    rows = []
    t0 = time.time()
    for name, (forecaster, researcher) in chosen.items():
        bot = make_bot(name, forecaster, researcher)
        reports = await bot.forecast_questions(questions, return_exceptions=True)
        exp, gaps, fails = [], [], 0
        for (q, mkt), r in zip(markets, reports):
            if isinstance(r, BaseException):
                fails += 1
                continue
            p = float(r.prediction)
            exp.append(expected_baseline(p, mkt))
            gaps.append(abs(p - mkt))
        rows.append((name, len(exp), st.mean(exp) if exp else float("nan"), st.mean(gaps) if gaps else float("nan"), fails))
        print(f"  done {name}: n={len(exp)} exp_baseline={rows[-1][2]:.1f} mean|p-market|={rows[-1][3]:.3f} fails={fails}", flush=True)

    ceiling = st.mean(expected_baseline(m, m) for _, m in markets)
    after = openrouter_usage()
    spent = (after["usage"] - before["usage"]) if before and after else None
    print("\n=== 市场价为参照的期望 Baseline 分（越高越好；市场自身 = 上限，50% = 0）===")
    print(f"{'config':30s} {'n':>3s} {'exp_base':>9s} {'|p-mkt|':>8s} {'fail':>5s}")
    for name, n, b, g, f in sorted(rows, key=lambda r: -r[2]):
        print(f"{name:30s} {n:3d} {b:9.1f} {g:8.3f} {f:5d}")
    print(f"{'(market itself)':30s} {len(markets):3d} {ceiling:9.1f} {0.0:8.3f}")
    print(f"{'(always 50%)':30s} {len(markets):3d} {0.0:9.1f}")
    print(f"\nwall {(time.time()-t0)/60:.1f} min; OpenRouter spend this run: " + (f"${spent:.2f}" if spent is not None else "n/a"))


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    asyncio.run(main())
