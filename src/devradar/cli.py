"""Verified local operator entrypoints for ingestion and pending-run work."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
import time
from collections.abc import Sequence
from dataclasses import asdict
from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from devradar.auth.service import hash_password
from devradar.automation.worker import work_one_source_recipe
from devradar.ingestion.models import CrawlRunStatus
from devradar.ingestion.runner import IngestionRunError
from devradar.intelligence.embeddings import (
    EMBEDDING_MODEL_ID,
    EMBEDDING_MODEL_REVISION,
    LocalEmbeddingModel,
    backfill_job_embeddings,
    download_embedding_model,
    get_embedding_model_path,
)
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


def _embedding_batch_size(value: str) -> int:
    parsed = _positive_int(value)
    if parsed > 1_000:
        raise argparse.ArgumentTypeError("embedding batch size must not exceed 1000")
    return parsed


def _poll_seconds(value: str) -> int:
    parsed = _positive_int(value)
    if parsed > 300:
        raise argparse.ArgumentTypeError("poll seconds must not exceed 300")
    return parsed


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="devradar")
    subparsers = parser.add_subparsers(dest="command", required=True)
    recipe_worker = subparsers.add_parser(
        "source-recipe-worker",
        help="poll previews and enabled localhost source recipes",
    )
    recipe_worker.add_argument(
        "--deadline-minutes",
        type=_deadline_minutes,
        default=60,
        help="hard worker deadline from now (1..360, default 60)",
    )
    recipe_worker.add_argument(
        "--poll-seconds",
        type=_poll_seconds,
        default=_poll_seconds(os.environ.get("DEVRADAR_SOURCE_RECIPE_POLL_SECONDS", "10")),
        help="sleep between empty polls (1..300, default 10)",
    )
    recipe_worker.add_argument(
        "--once",
        action="store_true",
        help="poll once and exit after at most one worker cycle",
    )
    subparsers.add_parser(
        "download-embedding-model",
        help="download the fixed local embedding model revision",
    )
    subparsers.add_parser(
        "auth-hash-password",
        help="read an operator password securely and print its password hash",
    )
    embeddings = subparsers.add_parser(
        "embed-jobs",
        help="embed a bounded batch of canonical jobs with the fixed local model",
    )
    embeddings.add_argument(
        "--max-items",
        type=_embedding_batch_size,
        default=100,
        help="maximum current jobs to embed (default 100)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    configure_structured_logging()
    if args.command == "auth-hash-password":
        try:
            password = getpass.getpass("Password: ")
            print(hash_password(password))
        except (EOFError, KeyboardInterrupt):
            return 130
        except ValueError:
            print(
                json.dumps(
                    {
                        "error": {
                            "code": "auth_password_invalid",
                            "message": "Password could not be hashed safely.",
                        }
                    }
                ),
                file=sys.stderr,
            )
            return 1
        return 0
    if args.command == "download-embedding-model":
        try:
            download_embedding_model(get_embedding_model_path())
        except Exception:
            print(
                json.dumps(
                    {
                        "error": {
                            "code": "embedding_model_download_failed",
                            "message": "Fixed embedding model could not be downloaded safely.",
                        }
                    }
                ),
                file=sys.stderr,
            )
            return 1
        print(
            json.dumps(
                {
                    "model": EMBEDDING_MODEL_ID,
                    "revision": EMBEDDING_MODEL_REVISION,
                    "ready": True,
                },
                sort_keys=True,
            )
        )
        return 0

    engine: Engine | None = None
    try:
        engine = create_engine(get_database_url())
        with Session(engine) as session:
            if args.command == "embed-jobs":
                model = LocalEmbeddingModel(get_embedding_model_path())
                embedding_report = backfill_job_embeddings(
                    session,
                    embed_passage=model.embed_passage,
                    max_items=args.max_items,
                )
                print(json.dumps(asdict(embedding_report), sort_keys=True))
                return 0

            if args.command == "source-recipe-worker":
                deadline = datetime.now(UTC) + timedelta(minutes=args.deadline_minutes)
                previews_processed = 0
                runs_processed = 0
                recipe_last_status: CrawlRunStatus | None = None
                while datetime.now(UTC) < deadline:
                    work_result = work_one_source_recipe(session, deadline=deadline)
                    if work_result is None:
                        if args.once:
                            break
                        time.sleep(args.poll_seconds)
                        continue
                    if work_result.preview_processed:
                        previews_processed += 1
                    if work_result.orchestration is not None:
                        runs_processed += len(work_result.orchestration.reports)
                        recipe_last_status = work_result.orchestration.final_report.status
                    if args.once:
                        break
                print(
                    json.dumps(
                        {
                            "lastStatus": (
                                recipe_last_status.value if recipe_last_status else None
                            ),
                            "previewsProcessed": previews_processed,
                            "runsProcessed": runs_processed,
                        },
                        sort_keys=True,
                    )
                )
                return 0 if recipe_last_status in {None, CrawlRunStatus.SUCCEEDED} else 1
            else:
                raise AssertionError("argparse accepted an unsupported command")
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
        if args.command == "embed-jobs":
            error_payload = {
                "code": "embedding_failed",
                "message": "Embedding batch could not start or complete safely.",
            }
        else:
            error_payload = {
                "code": "ingestion_failed",
                "message": "Ingestion could not start or complete safely.",
            }
        print(
            json.dumps({"error": error_payload}),
            file=sys.stderr,
        )
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
