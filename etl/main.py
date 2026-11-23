import os
import logging

from apscheduler.schedulers.blocking import BlockingScheduler

from extract import extract_all
from transform import transform
from load import ensure_schema, load_all

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
log = logging.getLogger("etl")


def run_etl():
    log.info("ETL run started")
    try:
        raw = extract_all()
        data = transform(raw)
        load_all(data)
        log.info("ETL run completed")
    except Exception:
        log.exception("ETL run failed")


if __name__ == "__main__":
    ensure_schema()
    run_etl()

    interval = int(os.environ.get("ETL_INTERVAL_SECONDS", "300"))
    log.info("Scheduling ETL every %d seconds", interval)
    scheduler = BlockingScheduler()
    scheduler.add_job(run_etl, "interval", seconds=interval)
    scheduler.start()
