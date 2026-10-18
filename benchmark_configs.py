"""
Phase 2: compare bot configurations against the Metaculus community prediction.

forecasting-tools' Benchmarker pulls N currently-open *binary* questions (>=30 forecasters,
community prediction visible) and scores each bot's forecast by its expected baseline score
if the community prediction were the truth. No leakage, no waiting for resolution. Nothing
is published. 100+ questions separate bots reliably; 20 only separates large gaps - this is
the cheap first pass.

    .venv/bin/python benchmark_configs.py --questions 20            # all four configs
    .venv/bin/python benchmark_configs.py --questions 20 --only A D

Costs real money on the OpenRouter key: ~$0.15-0.40 per question per config.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import time

import dotenv

dotenv.load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

from bot_helpers import silence_noisy_dependencies  # noqa: E402

silence_noisy_dependencies()

from datetime import timedelta  # noqa: E402

import pendulum  # noqa: E402
from forecasting_tools import Benchmarker, GeneralLlm, MetaculusClient  # noqa: E402
from forecasting_tools.helpers.metaculus_client import ApiFilter  # noqa: E402

from budget_guard import check_budget, openrouter_usage  # noqa: E402
from main import FallTemplateBot2026  # noqa: E402


async def fetch_benchmark_questions(n: int):
    """Open binary questions whose community prediction (CP) is already revealed.

    Metaculus hides the CP from *bot* accounts on essentially every question (anti-copying), so
    this read-only fetch uses the human account's token (METACULUS_HUMAN_TOKEN). forecasting-tools'
    own random sampler also pages deep into the feed and hits rate limits, so we walk newest-first.
    Nothing is ever posted with this token.
    """
    human_token = os.getenv("METACULUS_HUMAN_TOKEN")
    if not human_token or human_token == "REPLACE_ME":
        raise SystemExit("METACULUS_HUMAN_TOKEN not set: the bot account cannot see community predictions")
    now = pendulum.now(tz="UTC")
    api_filter = ApiFilter(
        allowed_statuses=["open"],
        allowed_types=["binary"],
        num_forecasters_gte=30,
        cp_reveal_time_lt=now,
        community_prediction_exists=True,
        group_question_mode="exclude",
        open_time_gt=now - timedelta(days=365),
    )
    client = MetaculusClient(token=human_token)
    questions = await client.get_questions_matching_filter(
        api_filter, num_questions=n, randomly_sample=False, error_if_question_target_missed=False
    )
    return [q for q in questions if q.community_prediction_at_access_time is not None]

OR = "openrouter/"
HIGH = {"extra_body": {"reasoning": {"effort": "high"}}}  # OpenRouter's native reasoning switch
# OpenAI / Anthropic / Google return 403 for this account (region enforcement), so the
# candidates are the strongest providers that answered the 2026-10-18 probe.
GROK = OR + "x-ai/grok-4.7"                       # $2 / $6 per M
DEEPSEEK = OR + "deepseek/deepseek-v4-pro"        # $0.21 / $0.42 per M
KIMI = OR + "moonshotai/kimi-k3"                  # $0.30 / $11.94 per M (pricey output)
FLASH = OR + "deepseek/deepseek-v4.1-flash"       # parser / summarizer, $0.04 / $0.14
FLASH_ONLINE = FLASH + ":online"                  # research via OpenRouter web plugin
GROK_ONLINE = GROK + ":online"


def llm(model: str, **kw) -> GeneralLlm:
    return GeneralLlm(model=model, timeout=300, allowed_tries=2, **kw)


# name -> (forecaster, researcher). Parser/summarizer are DeepSeek flash everywhere.
CONFIGS: dict[str, tuple[GeneralLlm, GeneralLlm | str]] = {
    "A_grok47_high__flash_online": (llm(GROK, **HIGH), llm(FLASH_ONLINE)),
    "B_deepseekv4pro_high__flash_online": (llm(DEEPSEEK, **HIGH), llm(FLASH_ONLINE)),
    "C_kimik3_high__flash_online": (llm(KIMI, **HIGH), llm(FLASH_ONLINE)),
    "D_grok47_high__no_research": (llm(GROK, **HIGH), "no_research"),
}


def make_bot(name: str, forecaster: GeneralLlm, researcher: GeneralLlm | str) -> FallTemplateBot2026:
    # Distinct subclass per config so the benchmark report labels them apart.
    cls = type(f"Bot_{name}", (FallTemplateBot2026,), {})
    return cls(
        research_reports_per_question=1,
        predictions_per_research_report=3,
        use_research_summary_to_forecast=False,
        publish_reports_to_metaculus=False,
        folder_to_save_reports_to=None,
        skip_previously_forecasted_questions=False,
        llms={
            "default": forecaster,
            "researcher": researcher,
            "parser": llm(FLASH),
            "summarizer": llm(FLASH),
        },
    )


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--questions", type=int, default=20)
    ap.add_argument("--only", nargs="*", help="config name prefixes to run, e.g. A D")
    args = ap.parse_args()

    check_budget(strict=True)
    before = openrouter_usage()

    chosen = {k: v for k, v in CONFIGS.items() if not args.only or any(k.startswith(p) for p in args.only)}
    bots = [make_bot(name, f, r) for name, (f, r) in chosen.items()]

    questions = await fetch_benchmark_questions(args.questions)
    if not questions:
        raise SystemExit("no benchmark questions found")
    print(f"configs: {list(chosen)}  questions: {len(questions)}")
    for q in questions:
        print(f"  - {(q.question_text or '')[:80]}  CP={q.community_prediction_at_access_time}")
    print()

    os.makedirs("benchmarks", exist_ok=True)
    bench = Benchmarker(
        forecast_bots=bots,
        questions_to_use=questions,
        file_path_to_save_reports="benchmarks/",
        concurrent_question_batch_size=4,
    )
    t0 = time.time()
    results = await bench.run_benchmark()

    after = openrouter_usage()
    spent = (after["usage"] - before["usage"]) if before and after else None
    print("\n=== 配置对比（分数 = 以社区预测为真值的期望 baseline 分，越高越好） ===")
    print(f"{'config':34s} {'n':>4s} {'score':>8s} {'fail':>5s} {'min':>6s}")
    for b in sorted(results, key=lambda b: -(b.average_expected_baseline_score if b.forecast_reports else -1e9)):
        score = b.average_expected_baseline_score if b.forecast_reports else float("nan")
        print(f"{b.forecast_bot_class_name.removeprefix('Bot_'):34s} {len(b.forecast_reports):4d} {score:8.2f} {len(b.failed_report_errors):5d} {b.time_taken_in_minutes or 0:6.1f}")
    print(f"\nwall time {(time.time()-t0)/60:.1f} min; OpenRouter spend this run: "
          + (f"${spent:.2f}" if spent is not None else "n/a") + f"; reports in benchmarks/")


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    asyncio.run(main())
