import argparse
import json
import os
import signal
from datetime import date, timedelta
from threading import Event
from time import monotonic

from etl.db import connect, initialize, pipeline_lock
from etl.load import load_core, refresh_market
from ml.train import run_model


def log_stage(stage, **fields):
    print(json.dumps({"stage": stage, **fields}, ensure_ascii=False, default=str), flush=True)


def run(as_of: date, start_date=None, end_date=None, skip_ml=False):
    started = monotonic()
    with connect() as connection, pipeline_lock(connection):
        initialize(connection)
        bounds = connection.execute(
            "SELECT min(loading_date) AS start, max(loading_date) AS last FROM raw.prices"
        ).fetchone()
        if bounds["start"] is None:
            raise ValueError("Source raw.prices is empty")
        start_date = start_date or bounds["start"]
        end_date = end_date or bounds["last"] + timedelta(days=1)
        counts = load_core(connection, start_date, end_date)
        log_stage("core", start_date=start_date, end_date=end_date, **counts)
        count = refresh_market(connection, as_of)
        log_stage("mart", rows=count, as_of=as_of)
        if not skip_ml:
            summary = run_model(connection, as_of)
            log_stage("ml", model=summary["model_name"], train=summary["train_count"],
                      test=summary["test_count"], future=summary["future_count"], **summary["metrics"])
    log_stage("complete", seconds=round(monotonic() - started, 2))


def main():
    parser = argparse.ArgumentParser(description="Load a window, refresh market cards and score deals")
    parser.add_argument("--as-of", type=date.fromisoformat, default=os.getenv("AS_OF", "2026-10-26"))
    parser.add_argument("--start-date", type=date.fromisoformat)
    parser.add_argument("--end-date", type=date.fromisoformat)
    parser.add_argument("--skip-ml", action="store_true")
    parser.add_argument("--once", action="store_true", help="Run once instead of the daily schedule")
    args = parser.parse_args()
    interval = 0 if args.once else int(os.getenv("RUN_INTERVAL_SECONDS", "86400"))
    if interval < 0:
        parser.error("RUN_INTERVAL_SECONDS cannot be negative")
    stopped = Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_: stopped.set())
    while True:
        run(args.as_of, args.start_date, args.end_date, args.skip_ml)
        if interval == 0 or stopped.wait(interval):
            return


if __name__ == "__main__":
    main()
