# V5-003 Secure CV Upload Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development and security-and-hardening. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a local-gated, ephemeral CV upload that produces a sanitized ResumeProfile without retaining raw file/text.

**Architecture:** Add one `matching`-owned ResumeProfile model and migration, one bounded parser module, and three owner-scoped REST endpoints. Keep parsing outside long DB transactions; persist only structured fields and hashes.

**Tech Stack:** Python 3.13, FastAPI multipart, pypdf, stdlib zipfile/xml/hashlib, SQLAlchemy/Alembic, PostgreSQL, pytest.

---

### Task 1: Add parser RED fixtures and dependency pins

**Files:** `tests/test_resume_profile_parser.py`, `requirements.in`, `requirements-dev.in`.

- [x] Test PDF/DOCX valid extraction and negative MIME/signature/size/path traversal/zip member limits first; run targeted pytest and observe import/behavior failure.
- [x] Add `pypdf==6.16.1` and `python-multipart==0.0.32` to `requirements.in`, regenerate both lock files with pinned pip-tools and clean-install. These exact releases were verified against their PyPI provenance on 2026-08-22.

### Task 2: Implement bounded parser and profile extraction

**Files:** Create `src/devradar/matching/resume_profile_parser.py` and `src/devradar/matching/__init__.py`.

- [x] Implement `parse_resume(filename, content_type, payload)` with fixed caps, magic checks, safe PDF/DOCX parser, SHA-256 content hash and `ResumeProfileDraft`.
- [x] Never log/echo payload/text; return allow-listed typed errors only.
- [x] Run targeted parser tests and Ruff/mypy.

### Task 3: Add domain model/migration with PostgreSQL RED→GREEN

**Files:** Create `src/devradar/matching/models.py`; add a new Alembic revision; update `migrations/env.py`; create `tests/integration/test_resume_profiles.py`.

- [x] Write schema/constraint/idempotency/expiry/delete/owner-isolation tests against fresh PostgreSQL.
- [x] Add `resume_profiles` with UUID, owner hash, content hash, parser/source, JSONB skills/roles/locations, years, timestamps, expiry/deleted fields; unique active replay key and indexes.
- [x] Run RED, implement migration/model, then GREEN plus `alembic check`.

### Task 4: Add owner-scoped REST endpoints

**Files:** Create `src/devradar/api/resume_profiles.py`; update `src/devradar/api/router.py`, `docs/API.md`.

- [x] Write route tests for default-disabled gate, missing/short owner, valid upload, wrong MIME, `413`, `404` owner mismatch, GET and DELETE.
- [x] Implement `X-DevRadar-Owner` validation, `DEVRADAR_CV_LOCAL_ENABLED` gate, parser call, idempotent insert, sanitized response and 24h expiry behavior.
- [x] Run targeted/default/PostgreSQL API tests.

### Task 5: Integrate docs/observability and verify

**Files:** `README.md`, `AGENTS.md`, `docs/DOMAIN_MODEL.md`, `docs/ARCHITECTURE.md`, `docs/ROADMAP.md`, `docs/evidence/V5-003-secure-cv-upload.md`, ignored `TASK_BOARD.md`.

- [x] Document local-only boundary and exact env setup without secrets.
- [x] Record metrics/status codes without raw PII; update V5-003 Done and V5-004 Ready.
- [x] Run full default/PostgreSQL/static/npm/Markdown/security gates and commit.
