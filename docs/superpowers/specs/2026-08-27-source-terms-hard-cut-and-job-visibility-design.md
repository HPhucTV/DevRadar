# Source terms hard cut and post-import Job visibility

## Status

Approved by the product owner on 2026-08-27. Implementation pending.

## Problem

SourceRecipe currently stores and publishes versioned source terms notice/evidence and can require exact
owner acknowledgement before preview, enable, run or document import. The acknowledgement does not grant
permission and cannot override access controls, but it adds persistence, API, workflow and UI states.

Separately, a completed local import can look unsuccessful because the completion surface returns the
operator to SourceRecipe management. Runtime evidence showed the data path was healthy:

    latest two runs: succeeded / incomplete / 10 found each
    first run: 9 new canonical Jobs after source-scoped dedup
    second run: 9 updated
    PostgreSQL: 9 Jobs / 18 RawJobSnapshots for the target source
    Jobs API: 9/9 target-source Jobs, all active
    Jobs dashboard: target jobs visible at the top of the result

The missing-data symptom is therefore a navigation/visibility problem, not persistence loss.

## Goals

- Remove all active runtime terms notice/acknowledgement behavior.
- Let successful preview move directly to ready without an extra confirmation.
- Preserve every technical crawler barrier and data safety invariant.
- Make completed import/crawl results discoverable from their completion surface.
- Preserve existing recipe/source/job/run data during migration.

## Non-goals

- No CAPTCHA, authentication, paywall, anti-bot, access-denial or SSRF bypass.
- No arbitrary URL fetch API or public mutation exposure.
- No legal/permission certification or terms analysis inside DevRadar.
- No reset/purge of existing SourceRecipe, Source, Job, Snapshot, Run or JobChange data.
- No new framework, service, queue or dependency.
- Historical ADR/source-review evidence is not deleted or rewritten.

## Domain and persistence hard cut

Remove active SourceRecipe terms fields:

    terms_notice
    terms_notice_version
    terms_evidence_url
    terms_reviewed_at
    terms_acknowledged_at

Remove the SourceRecipe terms enum/check constraint and all model/draft fields. Also remove
sources.terms_reviewed_at and the Source API termsReviewedAt field. Replace
ck_sources_approved_has_policy_reviews with an approved-source technical check that requires only
robots_reviewed_at. Keep robots_reviewed_at, route policy and access-control behavior.

Remove terms_reviewed_at from SourceRegistration and change next-review validation to compare only the
robots review timestamp. Historical source review Markdown remains evidence, not runtime registry data.

Migration requirements:

- forward migration from current Alembic head;
- downgrade recreates removed columns/constraints with safe nullable/default semantics for rollback tests;
- no source-derived graph deletion;
- migration round-trip and schema drift tests;
- deploy/one-click migration runs while API/crawler workers are stopped or not claiming work.

## REST and OpenAPI contract

Remove from SourceRecipe create/patch/response:

    acknowledgedNoticeVersion
    termsNotice
    termsNoticeVersion
    termsEvidenceUrl
    termsReviewedAt
    termsAcknowledgementRequired
    termsAcknowledged

Remove termsReviewedAt from the Source response as well.

Remove acknowledgement-specific error codes and PATCH branch. Source catalog entries retain only bounded
presentation/URL shortcut fields that are actively used; terms review/evidence fields disappear.

Document import response gains a server-derived sourceId alongside crawlRunId and existing counters.
Clients must not supply sourceId.

Privacy contract removes the terms acknowledgement/owner-override claim and changes policyVersion from
privacy-v2 to privacy-v3 so stale clients fail visibly instead of accepting a partially changed response.

FastAPI-generated OpenAPI remains the wire source of truth. API docs and contract tests change in the same
commit as code.

## Workflow behavior

### Create and preview

1. Create recipe from bounded HTTPS URL and deterministic config.
2. Request bounded preview.
3. Preview success with 3–5 valid candidates transitions directly to ready.
4. Visual mapping/route confirmation can still be required when extraction/route boundary is incomplete.
5. No terms notice, acknowledgement state or acknowledgement command exists.

### Enable, run and import

Enable/run/import validate:

- owned/non-retired recipe and allowed lifecycle;
- successful current preview/config/mapping where required;
- cooldown, quarantine and active-work constraints;
- exact host/path, SSRF/redirect and content/size/budget rules.

They do not resolve terms catalog data, compare notice versions or inspect acknowledgement timestamps.
Removing notice-version input changes the recipe config hash schema. New and migrated recipes use
source-recipe-config-v2; parser version remains unchanged because extraction semantics do not change.
Regression must prove old completed data stays readable while new work uses the new hash.

## Post-import visibility

Jobs page accepts bounded sourceId:

- server page parses one UUID only; invalid/multi-value input is ignored rather than forwarded;
- listJobs receives sourceId with existing query/location/page filters;
- filter form preserves sourceId in a hidden input;
- result heading remains truthful to filtered pagination.

Source workflow:

- after successful document import, show View imported jobs;
- link target is /jobs?sourceId={response.sourceId};
- CTA is absent when import has not succeeded.

Any other completion client without a source ID opens /jobs, which is already sorted by newest
lastSeenAt. It must not guess a source ID from recipe names or listing URLs.

## Technical safety retained

The hard cut must leave these behaviors and negative tests unchanged:

- SourceRecipe feature disabled outside explicit localhost mode;
- HTTPS-only URL normalization and exact hostname/path boundary;
- DNS/IP/redirect SSRF policy;
- isolated browser restrictions and no persistent credentials;
- CAPTCHA/login/paywall/anti-bot/access denial/route escape hard stop;
- fixed budgets, sequential processing and no arbitrary proxy;
- document import type/size/UTF-8/route/challenge checks;
- provenance, idempotency, incomplete coverage and false-removal guards;
- auth/CSRF/owner isolation for mutations.

## UI removal

Delete from dashboard:

- terms notice panel, labels, evidence link and acknowledgement checkbox;
- acknowledgement-required success/error copy;
- terms-specific visual states and dictionary keys.

Retain the technical blocked state and explain barrier recovery without legal/terms language.

No empty placeholder or hidden disabled acknowledgement control remains in DOM. VI/EN dictionary parity and
accessibility tests remain required.

## Testing

### Migration/schema

- old head → new head → old head → new head;
- removed columns/constraints absent at new head;
- all SourceRecipe/Source/Job/Snapshot/Run rows retained;
- existing active Job counts unchanged.

### Backend/API

- create/preview/import without terms fields or acknowledgement;
- preview success directly ready;
- manual/scheduled run no notice drift gate;
- source catalog and privacy contract contain no terms fields;
- OpenAPI forbids removed request/response fields;
- technical barrier negative suite remains green.

### Web

- terms UI and dictionary keys absent;
- completed import CTA targets exact source-filtered Jobs route;
- Jobs page parses/preserves sourceId and returns only that source;
- malformed sourceId is not forwarded;
- VI/EN, keyboard, 375/768/1024/1440 and 200% text checks.

### Acceptance

Use one disposable recipe:

1. create without acknowledgement input;
2. preview to ready;
3. import controlled jobs;
4. follow completion CTA;
5. verify exact source-filtered Jobs result;
6. replay remains idempotent;
7. cleanup only disposable graph.

Never purge or mutate current TopCV evidence recipes during acceptance.

## Rollout

1. Commit ADR/spec only.
2. Write a TDD implementation plan with migration first and explicit contract inventory.
3. Implement backend/schema and pass PostgreSQL/OpenAPI gates.
4. Implement tracked dashboard visibility and terms UI removal.
5. Run local-client alignment outside tracked Git.
6. Run full default/PostgreSQL/static/web/Compose/browser/secret/supply-chain gates.
7. Push tracked backend/web/docs only after local-only leak gate.

## Remaining boundaries

- This decision removes application terms review; it does not assert that every operator-selected source is
  legally reusable.
- Historical source review records remain historical evidence, not runtime permission or technical config.
- Public HTTPS/provider deployment gates remain open and unchanged.
