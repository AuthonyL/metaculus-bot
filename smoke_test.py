"""
Offline smoke test: one hand-written binary question through research -> forecast -> parse,
nothing posted to Metaculus. Needs an LLM key (ANTHROPIC_API_KEY or OPENROUTER_API_KEY)
but NOT a METACULUS_TOKEN.

    .venv/bin/python smoke_test.py
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

import dotenv

dotenv.load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

from bot_helpers import silence_noisy_dependencies  # noqa: E402

silence_noisy_dependencies()

from forecasting_tools import BinaryQuestion  # noqa: E402

from bot_config import build_llms, describe_llms  # noqa: E402
from main import FallTemplateBot2026  # noqa: E402


def sample_question() -> BinaryQuestion:
    now = datetime.now(timezone.utc)
    return BinaryQuestion(
        question_text="Will the United States Federal Reserve cut its policy rate at its next scheduled FOMC meeting?",
        background_info="The FOMC sets the federal funds target range eight times a year. Markets price each meeting via fed funds futures.",
        resolution_criteria="Resolves Yes if the FOMC statement after its next scheduled meeting announces a lower target range than the current one.",
        fine_print="An inter-meeting move does not count. Resolves No if the range is unchanged or raised.",
        page_url="https://www.metaculus.com/questions/0/smoke-test/",
        id_of_post=0,
        id_of_question=0,
        close_time=now + timedelta(days=30),
        scheduled_resolution_time=now + timedelta(days=45),
        open_time=now - timedelta(days=1),
        published_time=now - timedelta(days=1),
    )


async def main() -> None:
    llms = build_llms()
    if llms is None:
        raise SystemExit("Set ANTHROPIC_API_KEY or OPENROUTER_API_KEY in .env first")
    print(f"Models: {describe_llms(llms)}\n")
    bot = FallTemplateBot2026(
        research_reports_per_question=1,
        predictions_per_research_report=2,  # keep the smoke test cheap
        publish_reports_to_metaculus=False,
        folder_to_save_reports_to="reports",
        skip_previously_forecasted_questions=False,
        llms=llms,
    )
    report = await bot.forecast_question(sample_question())
    print("\n=== SUMMARY ===\n", report.summary)
    print("\n=== EXPLANATION (first 3000 chars) ===\n", report.explanation[:3000])
    print("\n=== PREDICTION ===", report.prediction)
    print(f"\nreport saved under ./reports ; minor errors: {len(report.errors)} ; est. cost ${report.price_estimate}")


if __name__ == "__main__":
    asyncio.run(main())
