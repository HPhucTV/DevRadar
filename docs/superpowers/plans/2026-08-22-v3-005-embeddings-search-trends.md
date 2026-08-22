# V3-005 Embeddings, semantic search và skill trends — Implementation Plan

**Goal:** Implement ADR-009 local embedding persistence, exact semantic job search và evidence-backed skill analytics.

## Task 1 — Dependency/model boundary TDD

- Add red tests for bounded canonical input, fixed model identity, finite 384d output and missing model.
- Implement `intelligence.embeddings` with lazy FastEmbed import, fixed revision download and local-path inference.
- Pin FastEmbed/pgvector through `.in` files and regenerate hash locks; default tests never download model/network.

## Task 2 — pgvector persistence TDD

- Add `JobEmbedding` mapping and migration after V3-003 head.
- Change Compose database image to fixed pgvector 0.8.6 PostgreSQL 18.
- PostgreSQL tests cover extension/version, vector dimension, logical uniqueness, stale hash/model exclusion, exact cosine ordering and rollback.

## Task 3 — Backfill/operator path

- Add fixed model download and bounded `embed-jobs` CLI commands; no arbitrary model/URL.
- Backfill only missing current logical keys, provider call outside transaction, commit each accepted vector and return safe counters.
- Test idempotency, malformed vector and model unavailable behavior.

## Task 4 — Semantic/keyword API contract

- Extend `JobQuery` with bounded `query`, `searchMode`, `skill` and optional `relevanceScore` output.
- Unit/contract tests first; PostgreSQL integration verifies filtering, stable paging, model compatibility and no raw vector/path.
- Document additive API behavior and safe 503.

## Task 5 — Skills/trends API contract

- Add analytics router with typed filters/envelopes.
- Select latest compatible accepted extraction per current Job; aggregate bounded rows in application.
- Test denominator, analyzed coverage, empty cohort, status/source/time/granularity and stable ordering.

## Task 6 — Evidence and verification

- Update DOMAIN_MODEL, AI, API, ARCHITECTURE, OPERATIONS, README commands if verified, evidence and local task board.
- Run model smoke, PostgreSQL migration/integration/API, full tests, Ruff, format, mypy, pip check, Compose config/build where Docker is available and Markdown links.
- Commit V3-005; do not push until V3-006 closes V3.
