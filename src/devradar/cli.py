"""Verified local operator entrypoint for orchestrated on-demand ingestion."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from devradar.automation.orchestrator import orchestrate_source
from devradar.ingestion.models import CrawlRunStatus
from devradar.ingestion.runner import IngestionRunError, resolve_v1_source
from devradar.ingestion.source_registry import V1_SOURCE_REGISTRY
from devradar.platform.database import get_database_url
from devradar.platform.observability import configure_structured_logging


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


def _deadline_minutes(value: str) -> int:
    parsed = _positive_int(value)
    if parsed > 360:
        raise argparse.ArgumentTypeError("deadline minutes must not exceed 360")
    return parsed


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="devradar")
    subparsers = parser.add_subparsers(dest="command", required=True)
    crawl = subparsers.add_parser("crawl", help="run one approved source on demand")
    crawl.add_argument("--source", choices=V1_SOURCE_REGISTRY.keys(), required=True)
    crawl.add_argument(
        "--deadline-minutes",
        type=_deadline_minutes,
        default=60,
        help="hard run deadline from now (1..360, default 60)",
    )
    crawl.add_argument(
        "--max-items",
        type=_positive_int,
        help="process only the first N discovered items and mark coverage incomplete",
    )
    crawl.add_argument(
        "--idempotency-key",
        help="optional opaque key (1..200 characters) for safe operator retry",
    )
    return parser


def _json_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if hasattr(value, "value"):
        return value.value
    return value


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    configure_structured_logging()
    if args.command != "crawl":
        raise AssertionError("argparse accepted an unsupported command")
    engine: Engine | None = None
    try:
        resolved = resolve_v1_source(args.source)
        engine = create_engine(get_database_url())
        with Session(engine) as session:
            result = orchestrate_source(
                session,
                config=resolved.config,
                adapter=resolved.adapter,
                deadline=datetime.now(UTC) + timedelta(minutes=args.deadline_minutes),
                max_items=args.max_items,
                trigger_key=args.idempotency_key,
            )
            report = result.final_report
    except KeyboardInterrupt:
        return 130
    except IngestionRunError as error:
        print(
            json.dumps(
                {"error": {"code": error.code, "message": str(error)}},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 1
    except Exception:
        print(
            json.dumps(
                {
                    "error": {
                        "code": "ingestion_failed",
                        "message": "Ingestion could not start or complete safely.",
                    }
                }
            ),
            file=sys.stderr,
        )
        return 1
    finally:
        if engine is not None:
            engine.dispose()

    print(
        json.dumps(
            {key: _json_value(value) for key, value in asdict(report).items()},
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if report.status is CrawlRunStatus.SUCCEEDED else 1


if __name__ == "__main__":
    raise SystemExit(main())
