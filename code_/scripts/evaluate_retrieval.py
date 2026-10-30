"""Run the sampled retrieval quality check now and save the result for the admin dashboard.

The API already runs this once a day; use this script to run it on demand or from cron. The result goes to
the AgWeatherNet backend when AWN_BACKEND_URL and AWN_INTERNAL_KEY are set, otherwise to the local store.

    python -m scripts.evaluate_retrieval            # evaluate and save
    python -m scripts.evaluate_retrieval --dry-run  # evaluate and print only
"""

import argparse

import dotenv
from backend.analytics import retrieval_quality
from backend.analytics.awn_reporter import AwnUsageReporter
from backend.analytics.usage_store import UsageStore
from backend.databases.pgvector import PgVectorConnection


def main() -> None:
    """Evaluate the sample questions against the live vector store."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--samples", help="alternative sample questions file (default: retrieval_samples.yaml)")
    parser.add_argument("--dry-run", action="store_true", help="print the results without saving them")
    args = parser.parse_args()

    dotenv.load_dotenv()
    from backend.api import (
        _build_retriever,  # builds the same retriever the chat endpoint uses
    )

    retriever, *_ = _build_retriever()
    samples = retrieval_quality.load_samples(args.samples)
    run = retrieval_quality.evaluate(retriever.find_context, samples)

    for detail in run.details:
        mark = "PASS" if detail["passed"] else "FAIL"
        found = ", ".join(detail["found"]) or detail["error"] or "nothing"
        print(f"{mark}  [{detail['source']:<10}] {detail['question']}  (expected {detail['expected']}, found {found})")
    print(f"\n{run.passed} of {run.samples} sample questions found the right weather data ({run.score or 0:.0%}).")

    if not args.dry_run:
        reporter = AwnUsageReporter.from_env()
        store = reporter or UsageStore(lambda: PgVectorConnection().conn)
        store.record_quality_run(run.samples, run.passed, run.details)
        print(f"Saved to the dashboard{' at ' + reporter.base_url if reporter else ''}.")


if __name__ == "__main__":
    main()
