"""Measure the existing PostgreSQL claim path without running a real crawler."""

# The benchmark is intentionally runnable directly from a source checkout.
# Keep the local src path bootstrap before application imports.
# ruff: noqa: E402

from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from uuid import UUID, uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from sqlalchemy import delete, func, select
from sqlalchemy.engine import Engine, create_engine
from sqlalchemy.orm import Session

from devradar.ingestion.models import (
    CrawlRun,
    CrawlRunStatus,
    CrawlTriggerType,
    Source,
    SourceApprovalStatus,
    SourceHealthStatus,
)

DATABASE_ENV = "DEVRADAR_QUEUE_BENCHMARK_DATABASE_URL"
MAX_ITEMS = 1_000
MAX_WORKERS = 16


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--items", type=int, default=100)
    parser.add_argument("--workers", type=int, default=4)
    return parser


def _validate(items: int, workers: int) -> None:
    if not 1 <= items <= MAX_ITEMS:
        raise ValueError(f"items must be between 1 and {MAX_ITEMS}")
    if not 1 <= workers <= MAX_WORKERS:
        raise ValueError(f"workers must be between 1 and {MAX_WORKERS}")


def _benchmark_url() -> str:
    value = os.environ.get(DATABASE_ENV, "").strip()
    if not value:
        raise RuntimeError(
            f"{DATABASE_ENV} must point to a disposable migrated PostgreSQL database"
        )
    if "postgresql+psycopg://" not in value:
        raise RuntimeError(f"{DATABASE_ENV} must use postgresql+psycopg://")
    return value


def _seed(session: Session, items: int, principal: str) -> tuple[list[UUID], list[UUID]]:
    now = datetime.now(UTC)
    source_ids: list[UUID] = []
    run_ids: list[UUID] = []
    runs: list[CrawlRun] = []
    for _ in range(items):
        source_id = uuid4()
        source_ids.append(source_id)
        source = Source(
            id=source_id,
            name=f"benchmark-source-{source_id}",
            base_url="https://benchmark.invalid",
            adapter_key="benchmark",
            approval_status=SourceApprovalStatus.APPROVED,
            health_status=SourceHealthStatus.HEALTHY,
            rate_limit_policy={"requestsPerMinute": 1},
            allowed_hosts=["benchmark.invalid"],
            terms_reviewed_at=now,
            robots_reviewed_at=now,
        )
        run_id = uuid4()
        run_ids.append(run_id)
        trigger_key = f"benchmark:{run_id}"
        session.add(source)
        runs.append(
            CrawlRun(
                id=run_id,
                source_id=source_id,
                trigger_type=CrawlTriggerType.MANUAL,
                status=CrawlRunStatus.PENDING,
                trigger_key=trigger_key,
                requested_at=now,
                requested_by=principal,
                request_hash=hashlib.sha256(trigger_key.encode()).hexdigest(),
                adapter_version="benchmark-v1",
                config_version="benchmark-v1",
            )
        )
    session.flush()
    session.add_all(runs)
    session.commit()
    return source_ids, run_ids


def _claim_one(engine: Engine, principal: str) -> float | None:
    started = time.perf_counter()
    with Session(engine) as session:
        run = session.scalar(
            select(CrawlRun)
            .where(
                CrawlRun.status == CrawlRunStatus.PENDING,
                CrawlRun.trigger_type == CrawlTriggerType.MANUAL,
                CrawlRun.requested_by == principal,
            )
            .order_by(CrawlRun.requested_at.asc(), CrawlRun.id.asc())
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if run is None:
            session.rollback()
            return None
        run.status = CrawlRunStatus.RUNNING
        run.started_at = datetime.now(UTC)
        session.commit()
    return (time.perf_counter() - started) * 1000


def _claim_round(engine: Engine, workers: int, principal: str) -> list[float]:
    latencies: list[float] = []
    lock = Lock()

    def worker() -> None:
        empty_streak = 0
        while empty_streak < 3:
            latency = _claim_one(engine, principal)
            if latency is None:
                empty_streak += 1
                time.sleep(0.001)
                continue
            empty_streak = 0
            with lock:
                latencies.append(latency)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(worker) for _ in range(workers)]
        for future in futures:
            future.result()
    return latencies


def _remaining(session: Session, principal: str) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(CrawlRun)
            .where(
                CrawlRun.status == CrawlRunStatus.PENDING,
                CrawlRun.requested_by == principal,
            )
        )
        or 0
    )


def run(items: int, workers: int) -> dict[str, object]:
    _validate(items, workers)
    engine = create_engine(_benchmark_url(), pool_size=max(workers + 2, 5), max_overflow=0)
    source_ids: list[UUID] = []
    principal = f"benchmark-{uuid4().hex[:16]}"
    try:
        with Session(engine) as session:
            source_ids, _ = _seed(session, items, principal)
        started = time.perf_counter()
        latencies = _claim_round(engine, workers, principal)
        for _ in range(5):
            with Session(engine) as session:
                if _remaining(session, principal) == 0:
                    break
            latencies.extend(_claim_round(engine, workers, principal))
        total_ms = (time.perf_counter() - started) * 1000
        with Session(engine) as session:
            remaining = _remaining(session, principal)
        if len(latencies) != items or remaining != 0:
            raise RuntimeError(
                f"benchmark did not claim all rows: claimed={len(latencies)} remaining={remaining}"
            )
        ordered = sorted(latencies)
        p95_index = min(len(ordered) - 1, max(0, int(len(ordered) * 0.95) - 1))
        return {
            "items": items,
            "workers": workers,
            "claimed": len(latencies),
            "totalMs": round(total_ms, 3),
            "throughputPerSecond": round(items / (total_ms / 1000), 3),
            "p50ClaimMs": round(statistics.median(ordered), 3),
            "p95ClaimMs": round(ordered[p95_index], 3),
            "maxClaimMs": round(max(ordered), 3),
        }
    finally:
        with Session(engine) as session:
            if source_ids:
                session.execute(delete(CrawlRun).where(CrawlRun.source_id.in_(source_ids)))
                session.execute(delete(Source).where(Source.id.in_(source_ids)))
                session.commit()
        engine.dispose()


def main() -> int:
    args = _parser().parse_args()
    try:
        print(json.dumps(run(args.items, args.workers), sort_keys=True))
    except (RuntimeError, ValueError) as error:
        print(json.dumps({"error": "queue_benchmark_failed", "message": str(error)}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
