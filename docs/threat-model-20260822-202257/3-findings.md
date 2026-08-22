# Security Findings

---

## Tier 1 — Direct Exposure (No Prerequisites)

*No Tier 1 findings identified for this repository.*

---

## Tier 2 — Conditional Risk (Authenticated / Single Prerequisite)

### FIND-01: Local owner header is not production authentication

| Attribute | Value |
|-----------|-------|
| SDL Bugbar Severity | Important |
| CVSS 4.0 | 7.1 (CVSS:4.0/AV:L/AC:L/AT:N/PR:N/UI:N/VC:H/VI:H/VA:N/SC:N/SI:N/SA:N) |
| CWE | [CWE-306](https://cwe.mitre.org/data/definitions/306.html): Missing Authentication for Critical Function |
| OWASP | A07:2025 – Authentication Failures |
| Exploitation Prerequisites | Local Process Access |
| Exploitability Tier | Tier 2 — Conditional Risk |
| Remediation Effort | Medium |
| Mitigation Type | Redesign |
| Component | FastAPI |
| Related Threats | [T01.S](2-stride-analysis.md#fastapi), [T02.E](2-stride-analysis.md#fastapi) |

#### Description

V5 protected endpoints accept an opaque `X-DevRadar-Owner` value and environment gates rather than an authenticated account with revocation and role claims. Any process able to reach the loopback API can mint or replay a token and invoke owner/operator operations.

#### Evidence

**Prerequisite basis:** FastAPI is host-bound to `127.0.0.1:8000` in [compose.yaml](../../compose.yaml), so exploitation requires a local process rather than an unauthenticated network client.

[src/devradar/api/resume_profiles.py](../../src/devradar/api/resume_profiles.py) implements `require_owner_hash()` over `X-DevRadar-Owner`; [src/devradar/api/alert_rules.py](../../src/devradar/api/alert_rules.py) uses `DEVRADAR_ALERTS_LOCAL_ENABLED` as a local write gate.

#### Remediation

Introduce the V6 authenticated session/token strategy from ADR-015 with server-side subject, role, expiry, revocation and CSRF protection. Keep the legacy owner header disabled for public deployment and migrate existing local data by explicit operator action.

#### Verification

Add API tests proving unauthenticated, expired, revoked, cross-owner and wrong-role requests receive safe `401/403` responses, then run a loopback browser smoke with a rotated test credential.

### FIND-02: Owner predicate coverage can regress across new routes

| Attribute | Value |
|-----------|-------|
| SDL Bugbar Severity | Important |
| CVSS 4.0 | 6.3 (CVSS:4.0/AV:L/AC:L/AT:N/PR:N/UI:N/VC:H/VI:L/VA:N/SC:N/SI:N/SA:N) |
| CWE | [CWE-862](https://cwe.mitre.org/data/definitions/862.html): Missing Authorization |
| OWASP | A01:2025 – Broken Access Control |
| Exploitation Prerequisites | Local Process Access |
| Exploitability Tier | Tier 2 — Conditional Risk |
| Remediation Effort | Medium |
| Mitigation Type | Standard Mitigation |
| Component | FastAPI |
| Related Threats | [T03.I](2-stride-analysis.md#fastapi), [T05.E](2-stride-analysis.md#fastapi) |

#### Description

Owner checks are implemented as route dependencies and query predicates, so a future mutation or read endpoint can accidentally omit them while still passing schema validation. Such a regression would expose another owner's profile, match or alert data to a local caller holding a different token.

#### Evidence

**Prerequisite basis:** The same loopback-only FastAPI binding in [compose.yaml](../../compose.yaml) makes local process access the minimum reachable prerequisite.

[src/devradar/api/resume_profiles.py](../../src/devradar/api/resume_profiles.py), [src/devradar/api/job_matches.py](../../src/devradar/api/job_matches.py) and [src/devradar/api/alert_rules.py](../../src/devradar/api/alert_rules.py) each repeat owner-scoped queries instead of using a centralized authenticated subject.

#### Remediation

Make the authenticated subject mandatory in a shared dependency, require an explicit owner/role policy for every sensitive resource, and add contract tests that exercise every endpoint with two owners.

#### Verification

Generate an endpoint matrix from the router and run negative tests for read, create, update, dispatch and delete paths; confirm no response contains `owner_hash`, raw CV text or embedding data.

### FIND-03: Synchronous alert work has no request rate limit

| Attribute | Value |
|-----------|-------|
| SDL Bugbar Severity | Moderate |
| CVSS 4.0 | 5.3 (CVSS:4.0/AV:L/AC:L/AT:N/PR:N/UI:N/VC:N/VI:N/VA:H/SC:N/SI:N/SA:N) |
| CWE | [CWE-770](https://cwe.mitre.org/data/definitions/770.html): Allocation of Resources Without Limits or Throttling |
| OWASP | A06:2025 – Insecure Design |
| Exploitation Prerequisites | Local Process Access |
| Exploitability Tier | Tier 2 — Conditional Risk |
| Remediation Effort | Medium |
| Mitigation Type | Standard Mitigation |
| Component | FastAPI |
| Related Threats | [T04.D](2-stride-analysis.md#fastapi) |

#### Description

Alert dispatch performs bounded provider calls inside the API request and has a fixed item limit but no per-owner or per-route rate budget. A local process can repeatedly occupy worker capacity while Discord is slow or unavailable.

#### Evidence

**Prerequisite basis:** [compose.yaml](../../compose.yaml) exposes FastAPI only on `127.0.0.1:8000`; no external listener lowers the prerequisite to local process access.

[src/devradar/alerts/service.py](../../src/devradar/alerts/service.py) caps a single dispatch at `MAX_DISPATCH_ITEMS`, while [src/devradar/alerts/delivery.py](../../src/devradar/alerts/delivery.py) retries up to three times synchronously; no rate-limit middleware exists in `src/devradar/api/`.

#### Remediation

Add a server-side token-bucket or fixed-window limit keyed by authenticated subject and route, with a concurrency budget and `Retry-After` response. Preserve the existing per-dispatch item cap.

#### Verification

Exercise concurrent dispatch requests in an integration test and verify the configured threshold returns `429`, connector calls remain bounded, and normal requests recover after the window.

### FIND-05: Same-origin BFF forwarding is not an authorization boundary

| Attribute | Value |
|-----------|-------|
| SDL Bugbar Severity | Moderate |
| CVSS 4.0 | 5.1 (CVSS:4.0/AV:L/AC:L/AT:N/PR:N/UI:N/VC:L/VI:L/VA:N/SC:N/SI:N/SA:N) |
| CWE | [CWE-441](https://cwe.mitre.org/data/definitions/441.html): Unintended Proxy or Intermediary ('Confused Deputy') |
| OWASP | A01:2025 – Broken Access Control |
| Exploitation Prerequisites | Local Process Access |
| Exploitability Tier | Tier 2 — Conditional Risk |
| Remediation Effort | Medium |
| Mitigation Type | Standard Mitigation |
| Component | NextJS |
| Related Threats | [T07.S](2-stride-analysis.md#nextjs), [T11.E](2-stride-analysis.md#nextjs) |

#### Description

The Next.js BFF forwards the caller's owner header to FastAPI and is intentionally not an identity provider. A same-host script that can call the BFF or inject a copied header can use it as a confused deputy unless FastAPI enforces the authenticated subject independently.

#### Evidence

**Prerequisite basis:** [web/package.json](../../web/package.json) binds Next.js to `127.0.0.1`, so a local process can reach the proxy but the public internet cannot.

[web/src/lib/backend-proxy.ts](../../web/src/lib/backend-proxy.ts) copies `x-devradar-owner`, and [web/src/lib/cv-match.ts](../../web/src/lib/cv-match.ts) accepts the token from browser memory.

#### Remediation

Terminate the authenticated session at the BFF, bind a server-side session subject to the forwarded request, strip caller-supplied identity headers, and retain FastAPI authorization as a second enforcement point.

#### Verification

Run browser and route tests with forged, missing and cross-owner headers; confirm the BFF cannot select an arbitrary owner and direct FastAPI calls still require the same authenticated subject.

### FIND-06: BFF requests lack a route-level rate and body budget

| Attribute | Value |
|-----------|-------|
| SDL Bugbar Severity | Moderate |
| CVSS 4.0 | 4.7 (CVSS:4.0/AV:L/AC:L/AT:N/PR:N/UI:N/VC:N/VI:N/VA:H/SC:N/SI:N/SA:N) |
| CWE | [CWE-400](https://cwe.mitre.org/data/definitions/400.html): Uncontrolled Resource Consumption |
| OWASP | A04:2025 – Insecure Design |
| Exploitation Prerequisites | Local Process Access |
| Exploitability Tier | Tier 2 — Conditional Risk |
| Remediation Effort | Low |
| Mitigation Type | Standard Mitigation |
| Component | NextJS |
| Related Threats | [T10.D](2-stride-analysis.md#nextjs) |

#### Description

Next.js route handlers proxy API calls but do not enforce a general request rate or response-size budget. Repeated local calls can consume the BFF's connection pool and rendering capacity even when downstream FastAPI validation is correct.

#### Evidence

**Prerequisite basis:** [web/package.json](../../web/package.json) uses `next dev/start --hostname 127.0.0.1`; the BFF has no external network reachability.

[web/src/lib/backend-proxy.ts](../../web/src/lib/backend-proxy.ts) forwards requests with `cache: no-store`, while route handlers under [web/src/app/api/devradar](../../web/src/app/api/devradar) do not define a shared rate limiter.

#### Remediation

Add authenticated subject and route budgets at the BFF, cap forwarded request/response bytes, and fail closed on upstream timeouts. Keep the API's own limits because the BFF is not the only caller.

#### Verification

Use a local load test with bounded concurrency and assert `429`/timeout behavior, stable memory, and no unbounded buffering in the route handlers.

### FIND-07: Response contracts could regress into profile or provider disclosure

| Attribute | Value |
|-----------|-------|
| SDL Bugbar Severity | Moderate |
| CVSS 4.0 | 5.0 (CVSS:4.0/AV:L/AC:L/AT:N/PR:N/UI:N/VC:H/VI:N/VA:N/SC:N/SI:N/SA:N) |
| CWE | [CWE-200](https://cwe.mitre.org/data/definitions/200.html): Exposure of Sensitive Information to an Unauthorized Actor |
| OWASP | A02:2025 – Security Misconfiguration |
| Exploitation Prerequisites | Local Process Access |
| Exploitability Tier | Tier 2 — Conditional Risk |
| Remediation Effort | Medium |
| Mitigation Type | Existing Control |
| Component | NextJS |
| Related Threats | [T08.T](2-stride-analysis.md#nextjs), [T09.I](2-stride-analysis.md#nextjs) |

#### Description

The BFF and UI depend on typed allow-listed responses, but a new field or error path could serialize owner hashes, raw CV text, embeddings or provider bodies. The leak would occur across the browser boundary even if database predicates remain correct.

#### Evidence

**Prerequisite basis:** Next.js is loopback-only per [web/package.json](../../web/package.json), so local process access is the minimum prerequisite.

[web/src/lib/cv-match.ts](../../web/src/lib/cv-match.ts) defines sanitized response guards, and [src/devradar/platform/observability.py](../../src/devradar/platform/observability.py) demonstrates the project's explicit field allow-list; neither proves future route additions safe automatically.

#### Remediation

Keep response DTOs closed by default, reject unknown fields, prohibit raw/provider fields in browser contracts, and add a privacy review gate for every new CV or alert response.

#### Verification

Contract tests should recursively scan serialized responses and errors for forbidden keys/content, including raw CV markers, `owner_hash`, vectors and webhook URLs.

---

## Tier 3 — Defense-in-Depth (Prior Compromise / Host Access)

### FIND-04: Alert delivery replay can amplify webhook traffic and expose the secret

| Attribute | Value |
|-----------|-------|
| SDL Bugbar Severity | Important |
| CVSS 4.0 | 6.1 (CVSS:4.0/AV:L/AC:H/AT:N/PR:H/UI:N/VC:H/VI:L/VA:L/SC:N/SI:N/SA:N) |
| CWE | [CWE-294](https://cwe.mitre.org/data/definitions/294.html): Authentication Bypass by Capture-replay |
| OWASP | A04:2025 – Cryptographic Failures |
| Exploitation Prerequisites | Host/OS Access |
| Exploitability Tier | Tier 3 — Defense-in-Depth |
| Remediation Effort | Medium |
| Mitigation Type | Custom Mitigation |
| Component | Discord |
| Related Threats | [T06.A](2-stride-analysis.md#fastapi), [T24.I](2-stride-analysis.md#discord), [T25.T](2-stride-analysis.md#discord), [T26.D](2-stride-analysis.md#discord), [T27.A](2-stride-analysis.md#discord) |

#### Description

The database delivery key prevents most duplicate sends, but a process crash after Discord accepts a message and before the status commit leaves a replay window. Repeated local dispatch can therefore amplify notifications, while a compromised process can use the webhook credential directly.

#### Evidence

**Prerequisite basis:** Discord is outbound-only and the webhook is read from process environment in [src/devradar/alerts/service.py](../../src/devradar/alerts/service.py); host/process access is required.

[src/devradar/alerts/delivery.py](../../src/devradar/alerts/delivery.py) documents bounded retries, and [src/devradar/alerts/models.py](../../src/devradar/alerts/models.py) stores delivery status/idempotency but no provider-side idempotency token or secret rotation mechanism.

#### Remediation

Keep the unique delivery identity, add an explicit in-flight lease and reconciliation state, rotate the Discord webhook through a managed secret, and make dispatch authorization/session policy authoritative.

#### Verification

Inject a crash between provider response and database commit, rerun dispatch, and verify the resulting state is observable and bounded. Rotate the webhook in a test environment and confirm the old value is rejected and never logged.

### FIND-08: Crawler allow-list and source policy can drift

| Attribute | Value |
|-----------|-------|
| SDL Bugbar Severity | Important |
| CVSS 4.0 | 6.8 (CVSS:4.0/AV:L/AC:H/AT:N/PR:H/UI:N/VC:L/VI:H/VA:N/SC:N/SI:N/SA:N) |
| CWE | [CWE-15](https://cwe.mitre.org/data/definitions/15.html): External Control of System or Configuration Setting |
| OWASP | A05:2025 – Injection |
| Exploitation Prerequisites | Host/OS Access |
| Exploitability Tier | Tier 3 — Defense-in-Depth |
| Remediation Effort | Medium |
| Mitigation Type | Standard Mitigation |
| Component | CLI |
| Related Threats | [T12.T](2-stride-analysis.md#cli), [T15.A](2-stride-analysis.md#cli), [T20.T](2-stride-analysis.md#approvedsources), [T23.A](2-stride-analysis.md#approvedsources) |

#### Description

The crawler is safe only while its immutable registry, database source configuration and approval records agree. A host-level change can widen an allow-list, route parser-controlled content into policy decisions, or continue crawling after a source's permission/terms change.

#### Evidence

**Prerequisite basis:** CLI is a non-listening crawler/worker process launched by the operator, so [compose.yaml](../../compose.yaml) and [src/devradar/cli.py](../../src/devradar/cli.py) establish Host/OS Access as the floor.

[src/devradar/ingestion/source_registry.py](../../src/devradar/ingestion/source_registry.py) validates reviewed hosts/path prefixes; [src/devradar/ingestion/snapshot_persistence.py](../../src/devradar/ingestion/snapshot_persistence.py) compares stored source policy; source approvals live under [docs/sources](../../docs/sources).

#### Remediation

Sign or checksum the registry/approval bundle, require an explicit operator review for policy changes, and quarantine a source when robots/terms evidence expires or differs from the stored record. Keep HTML/JD content outside policy and tool selection.

#### Verification

Mutate a source host/path, approval status and fixture content in tests; verify fail-closed resolution, quarantine, no outbound request and no policy change from prompt-like source text.

### FIND-09: Raw snapshots and unexpected source PII depend on host retention hygiene

| Attribute | Value |
|-----------|-------|
| SDL Bugbar Severity | Important |
| CVSS 4.0 | 6.0 (CVSS:4.0/AV:L/AC:H/AT:N/PR:H/UI:N/VC:H/VI:N/VA:N/SC:N/SI:N/SA:N) |
| CWE | [CWE-538](https://cwe.mitre.org/data/definitions/538.html): Insertion of Sensitive Information into Externally-Accessible File or Directory |
| OWASP | A02:2025 – Security Misconfiguration |
| Exploitation Prerequisites | Host/OS Access |
| Exploitability Tier | Tier 3 — Defense-in-Depth |
| Remediation Effort | Medium |
| Mitigation Type | Standard Mitigation |
| Component | CLI |
| Related Threats | [T13.I](2-stride-analysis.md#cli), [T22.I](2-stride-analysis.md#approvedsources) |

#### Description

Raw job snapshots are retained for provenance and can contain contact or personal data that was not expected by the adapter. A compromised workstation or copied database volume can therefore disclose more source content than the public API returns.

#### Evidence

**Prerequisite basis:** Snapshot persistence is performed by the host-launched CLI and PostgreSQL volume; [src/devradar/ingestion/snapshot_persistence.py](../../src/devradar/ingestion/snapshot_persistence.py) and [compose.yaml](../../compose.yaml) require Host/OS Access for this path.

[src/devradar/ingestion/snapshot_persistence.py](../../src/devradar/ingestion/snapshot_persistence.py) stores raw payload/provenance, while [docs/INGESTION.md](../../docs/INGESTION.md) defines retention and redaction expectations but no automated production retention job exists yet.

#### Remediation

Set an explicit raw snapshot retention window, redact known contact fields before durable storage where provenance permits, encrypt/permission the volume, and provide an operator purge/restore runbook.

#### Verification

Load a fixture containing email/phone data, run the retention job and backup restore drill, and verify expired/raw fields are deleted or redacted while canonical job provenance remains auditable.

### FIND-10: Crawler/browser resource budgets can be exhausted by hostile responses

| Attribute | Value |
|-----------|-------|
| SDL Bugbar Severity | Important |
| CVSS 4.0 | 6.0 (CVSS:4.0/AV:L/AC:H/AT:N/PR:H/UI:N/VC:N/VI:N/VA:H/SC:N/SI:N/SA:N) |
| CWE | [CWE-400](https://cwe.mitre.org/data/definitions/400.html): Uncontrolled Resource Consumption |
| OWASP | A04:2025 – Insecure Design |
| Exploitation Prerequisites | Host/OS Access |
| Exploitability Tier | Tier 3 — Defense-in-Depth |
| Remediation Effort | Medium |
| Mitigation Type | Existing Control |
| Component | CLI |
| Related Threats | [T14.D](2-stride-analysis.md#cli), [T20.T](2-stride-analysis.md#approvedsources), [T21.D](2-stride-analysis.md#approvedsources) |

#### Description

HTTP and Playwright adapters have time, byte, page and retry bounds, but a source that repeatedly approaches those limits can still consume the crawler container and operator workstation. Malformed HTML/JSON can also drive expensive parser paths before a safe failure is recorded.

#### Evidence

**Prerequisite basis:** CLI and the optional browser profile have no inbound listener and are started from the host, as shown by [compose.yaml](../../compose.yaml); Host/OS Access is the minimum prerequisite.

[src/devradar/ingestion/safe_http.py](../../src/devradar/ingestion/safe_http.py) bounds timeout/redirect/response size, [src/devradar/ingestion/adapters/momo.py](../../src/devradar/ingestion/adapters/momo.py) bounds browser actions, and [compose.yaml](../../compose.yaml) applies a crawler seccomp profile.

#### Remediation

Add explicit CPU/memory/pid limits and a total run budget at the container boundary, cap parser work per item, and quarantine sources whose complete run repeatedly exceeds the budget.

#### Verification

Run oversized, slow and malformed fixtures under the crawler profile; assert bounded wall time, memory/process count, safe failure counters and no false `removed` transitions.

### FIND-11: Local database defaults and broad migration privileges are unsafe for deployment

| Attribute | Value |
|-----------|-------|
| SDL Bugbar Severity | Important |
| CVSS 4.0 | 6.7 (CVSS:4.0/AV:L/AC:H/AT:N/PR:H/UI:N/VC:H/VI:H/VA:N/SC:N/SI:N/SA:N) |
| CWE | [CWE-798](https://cwe.mitre.org/data/definitions/798.html): Use of Hard-coded Credentials |
| OWASP | A05:2025 – Injection |
| Exploitation Prerequisites | Host/OS Access |
| Exploitability Tier | Tier 3 — Defense-in-Depth |
| Remediation Effort | High |
| Mitigation Type | Redesign |
| Component | PostgreSQL |
| Related Threats | [T16.I](2-stride-analysis.md#postgresql), [T17.T](2-stride-analysis.md#postgresql), [T19.E](2-stride-analysis.md#postgresql) |

#### Description

The Compose example intentionally uses `devradar_local_only` as a local password and runs migrations through the application image. Reusing that configuration in a public deployment would allow database compromise to bypass application owner predicates and alter canonical data.

#### Evidence

**Prerequisite basis:** PostgreSQL binds to `127.0.0.1:55432` in [compose.yaml](../../compose.yaml), and its credentials are supplied through `.env.example`; Host/OS Access is required in the current topology.

[compose.yaml](../../compose.yaml) contains the documented local default, [src/devradar/platform/database.py](../../src/devradar/platform/database.py) accepts one application URL, and [migrations](../../migrations) are the schema source of truth without a separately evidenced least-privilege production role.

#### Remediation

Use a managed secret with rotation, separate runtime and migration roles, restrict database network access, encrypt backups, and make deployment fail when local defaults are present.

#### Verification

Deploy with a generated secret and two roles, prove the runtime role cannot run DDL or read another tenant's records, and scan rendered Compose/deployment config for the local default.

### FIND-12: Raw/profile retention can create avoidable storage and query pressure

| Attribute | Value |
|-----------|-------|
| SDL Bugbar Severity | Moderate |
| CVSS 4.0 | 4.8 (CVSS:4.0/AV:L/AC:H/AT:N/PR:H/UI:N/VI:N/VA:H/VC:N/SC:N/SI:N/SA:N) |
| CWE | [CWE-799](https://cwe.mitre.org/data/definitions/799.html): Improper Restriction of Operations within the Bounds of a Memory Buffer |
| OWASP | A04:2025 – Insecure Design |
| Exploitation Prerequisites | Host/OS Access |
| Exploitability Tier | Tier 3 — Defense-in-Depth |
| Remediation Effort | Medium |
| Mitigation Type | Standard Mitigation |
| Component | PostgreSQL |
| Related Threats | [T18.D](2-stride-analysis.md#postgresql) |

#### Description

Raw snapshots, crawl history, embeddings and alert delivery rows grow with every run, while the current repository has no demonstrated automated production retention/partition policy. A host-level actor can also trigger repeated local runs to accelerate growth.

#### Evidence

**Prerequisite basis:** PostgreSQL is loopback-only in [compose.yaml](../../compose.yaml); creating or exhausting its volume requires host/process access.

[src/devradar/ingestion/models.py](../../src/devradar/ingestion/models.py), [src/devradar/intelligence/models.py](../../src/devradar/intelligence/models.py) and [src/devradar/alerts/models.py](../../src/devradar/alerts/models.py) define durable tables, while [docs/OPERATIONS.md](../../docs/OPERATIONS.md) records retention as a V6 gate rather than an implemented worker.

#### Remediation

Define per-entity retention, archive/purge schedules, bounded indexes and storage alerts; keep CV profile expiry separate from public job provenance.

#### Verification

Generate repeated crawl/profile/alert fixtures, execute purge and vacuum, and verify storage, query latency and provenance behavior against a documented budget.

### FIND-13: Local embedding artifact replacement can change rankings

| Attribute | Value |
|-----------|-------|
| SDL Bugbar Severity | Moderate |
| CVSS 4.0 | 5.7 (CVSS:4.0/AV:L/AC:H/AT:N/PR:H/UI:N/VC:N/VI:H/VA:L/SC:N/SI:N/SA:N) |
| CWE | [CWE-494](https://cwe.mitre.org/data/definitions/494.html): Download of Code Without Integrity Check |
| OWASP | A08:2025 – Software or Data Integrity Failures |
| Exploitation Prerequisites | Host/OS Access |
| Exploitability Tier | Tier 3 — Defense-in-Depth |
| Remediation Effort | Medium |
| Mitigation Type | Existing Control |
| Component | FastEmbed |
| Related Threats | [T32.T](2-stride-analysis.md#fastembed) |

#### Description

Semantic search and CV matching depend on a fixed local MiniLM artifact and revision. A host actor who replaces model files before startup can silently alter ranking and matching without changing application code.

#### Evidence

**Prerequisite basis:** FastEmbed is an in-process component with no listener; [src/devradar/intelligence/embeddings.py](../../src/devradar/intelligence/embeddings.py) loads the local artifact, so Host/OS Access is required.

[src/devradar/intelligence/embeddings.py](../../src/devradar/intelligence/embeddings.py) pins `EMBEDDING_MODEL_REVISION` and validates local-only loading; [compose.yaml](../../compose.yaml) packages the model into the image but has no external attestation at runtime.

#### Remediation

Verify the artifact SHA-256 at startup and in CI, sign/pin the container image, and fail closed when the revision or required file set differs from ADR-010.

#### Verification

Replace one artifact in a test image and confirm startup/API inference fails with a safe error; verify the expected fingerprint in the release manifest.

### FIND-14: Embedding runtime telemetry could disclose private text

| Attribute | Value |
|-----------|-------|
| SDL Bugbar Severity | Moderate |
| CVSS 4.0 | 5.0 (CVSS:4.0/AV:L/AC:H/AT:N/PR:H/UI:N/VC:H/VI:N/VA:N/SC:N/SI:N/SA:N) |
| CWE | [CWE-359](https://cwe.mitre.org/data/definitions/359.html): Exposure of Private Personal Information |
| OWASP | A02:2025 – Security Misconfiguration |
| Exploitation Prerequisites | Host/OS Access |
| Exploitability Tier | Tier 3 — Defense-in-Depth |
| Remediation Effort | Low |
| Mitigation Type | Existing Control |
| Component | FastEmbed |
| Related Threats | [T33.I](2-stride-analysis.md#fastembed) |

#### Description

Embedding receives structured resume/job text and is intentionally local, but an altered runtime or future provider configuration could emit telemetry or raw input to an external endpoint. This would bypass the CV privacy boundary without changing API responses.

#### Evidence

**Prerequisite basis:** [src/devradar/intelligence/embeddings.py](../../src/devradar/intelligence/embeddings.py) invokes in-process inference with no inbound listener; Host/OS Access is the minimum prerequisite.

The module sets `ORT_DISABLE_TELEMETRY=1` and constrains input lengths, while [docs/AI.md](../../docs/AI.md) prohibits raw CV logging; no network egress assertion is present in the Compose profile.

#### Remediation

Keep telemetry disabled, enforce local-files-only model loading, add egress deny policy for the inference process and prohibit raw input in diagnostics.

#### Verification

Run inference with network capture and assert zero external connections and no raw input in logs/traces; test a misconfigured provider path fails closed.

### FIND-15: Unbounded local inference can exhaust CPU or memory

| Attribute | Value |
|-----------|-------|
| SDL Bugbar Severity | Moderate |
| CVSS 4.0 | 5.9 (CVSS:4.0/AV:L/AC:H/AT:N/PR:H/UI:N/VC:N/VI:N/VA:H/SC:N/SI:N/SA:N) |
| CWE | [CWE-400](https://cwe.mitre.org/data/definitions/400.html): Uncontrolled Resource Consumption |
| OWASP | A04:2025 – Insecure Design |
| Exploitation Prerequisites | Host/OS Access |
| Exploitability Tier | Tier 3 — Defense-in-Depth |
| Remediation Effort | Medium |
| Mitigation Type | Standard Mitigation |
| Component | FastEmbed |
| Related Threats | [T34.D](2-stride-analysis.md#fastembed) |

#### Description

The model bounds text length and batch size, but repeated semantic queries or match generation still execute synchronously on the local process. A compromised or scripted local caller can consume all available CPU/memory and degrade the API.

#### Evidence

**Prerequisite basis:** FastEmbed has no listener and runs inside the API process; [src/devradar/intelligence/embeddings.py](../../src/devradar/intelligence/embeddings.py) and [src/devradar/matching/job_matches.py](../../src/devradar/matching/job_matches.py) establish Host/OS Access.

`MAX_QUERY_CHARS`, `MAX_EMBEDDING_TEXT_CHARS` and bounded match rows exist, but [compose.yaml](../../compose.yaml) does not yet show measured CPU/memory/pid limits for the API inference workload.

#### Remediation

Set container CPU/memory/pid budgets, limit concurrent inference, and return a bounded overload response without blocking unrelated read endpoints.

#### Verification

Run concurrent query/match pressure with resource limits enabled and confirm stable latency, `429/503` overload behavior and no process growth.

### FIND-16: Stale model/input identity can corrupt match interpretation

| Attribute | Value |
|-----------|-------|
| SDL Bugbar Severity | Moderate |
| CVSS 4.0 | 4.3 (CVSS:4.0/AV:L/AC:H/AT:N/PR:H/UI:N/VC:L/VI:L/VA:N/SC:N/SI:N/SA:N) |
| CWE | [CWE-345](https://cwe.mitre.org/data/definitions/345.html): Insufficient Verification of Data Authenticity |
| OWASP | A08:2025 – Software or Data Integrity Failures |
| Exploitation Prerequisites | Host/OS Access |
| Exploitability Tier | Tier 3 — Defense-in-Depth |
| Remediation Effort | Low |
| Mitigation Type | Existing Control |
| Component | FastEmbed |
| Related Threats | [T35.A](2-stride-analysis.md#fastembed) |

#### Description

Match rows are meaningful only when profile input version, job input schema, model revision and vector dimension agree. A host actor or migration mistake that bypasses those joins can present stale rankings as current evidence.

#### Evidence

**Prerequisite basis:** FastEmbed is local in-process and requires Host/OS Access to alter its artifact or stored identity.

[src/devradar/matching/job_matches.py](../../src/devradar/matching/job_matches.py) and [src/devradar/api/job_matches.py](../../src/devradar/api/job_matches.py) filter model/input identity, while [src/devradar/intelligence/models.py](../../src/devradar/intelligence/models.py) constrains vector metadata.

#### Remediation

Make identity joins and stale-hash checks mandatory at read and write boundaries, fail closed on unknown revisions, and expose only the validated identity in the UI.

#### Verification

Insert stale/mismatched rows in PostgreSQL fixtures and confirm they are excluded, regenerated or rejected; verify API output cannot claim compatibility for an unknown revision.

### FIND-17: DeepSeek key and synthetic boundary are host-trust assumptions

| Attribute | Value |
|-----------|-------|
| SDL Bugbar Severity | Important |
| CVSS 4.0 | 5.8 (CVSS:4.0/AV:L/AC:H/AT:N/PR:H/UI:N/VC:H/VI:H/VA:N/SC:N/SI:N/SA:N) |
| CWE | [CWE-922](https://cwe.mitre.org/data/definitions/922.html): Insecure Storage of Sensitive Information |
| OWASP | A02:2025 – Security Misconfiguration |
| Exploitation Prerequisites | Host/OS Access |
| Exploitability Tier | Tier 3 — Defense-in-Depth |
| Remediation Effort | Medium |
| Mitigation Type | Transfer Risk |
| Component | DeepSeek |
| Related Threats | [T28.I](2-stride-analysis.md#deepseek), [T29.T](2-stride-analysis.md#deepseek) |

#### Description

The DeepSeek integration is intentionally a synthetic-only development spike, but its API key and local environment file remain host secrets. A future caller could also accidentally cross the boundary and send real JD/CV content to the provider.

#### Evidence

**Prerequisite basis:** DeepSeek is outbound-only and invoked by [src/devradar/intelligence/deepseek_spike.py](../../src/devradar/intelligence/deepseek_spike.py); Host/OS Access is required to read the key or alter the caller.

[src/devradar/intelligence/deepseek_spike.py](../../src/devradar/intelligence/deepseek_spike.py) reads `DEVRADAR_DEEPSEEK_API_KEY` from bounded `.env.local`, rejects tools/thinking output and limits response bytes; [docs/AI.md](../../docs/AI.md) marks the boundary synthetic-only.

#### Remediation

Rotate any exposed key, keep it in a secret manager outside Git, enforce a synthetic fixture identifier at the call boundary, and deny production imports from the spike module.

#### Verification

Scan Git, logs and environment dumps for the key; run a negative test with real-looking JD/CV input and confirm the request is rejected before network I/O.

### FIND-18: DeepSeek spike can consume quota or treat fixture text as policy

| Attribute | Value |
|-----------|-------|
| SDL Bugbar Severity | Moderate |
| CVSS 4.0 | 4.6 (CVSS:4.0/AV:L/AC:H/AT:N/PR:H/UI:N/VC:N/VI:L/VA:L/SC:N/SI:N/SA:N) |
| CWE | [CWE-400](https://cwe.mitre.org/data/definitions/400.html): Uncontrolled Resource Consumption |
| OWASP | A06:2025 – Insecure Design |
| Exploitation Prerequisites | Host/OS Access |
| Exploitability Tier | Tier 3 — Defense-in-Depth |
| Remediation Effort | Low |
| Mitigation Type | Existing Control |
| Component | DeepSeek |
| Related Threats | [T30.D](2-stride-analysis.md#deepseek), [T31.A](2-stride-analysis.md#deepseek) |

#### Description

The spike is opt-in and bounded to four synthetic cases, but repeated invocations can spend provider quota and prompt-like fixture text can be mistaken for instructions if the validator boundary changes. The result must never select tools or mutate production policy.

#### Evidence

**Prerequisite basis:** [src/devradar/intelligence/deepseek_spike.py](../../src/devradar/intelligence/deepseek_spike.py) is a local CLI module with no listener; Host/OS Access is the minimum prerequisite.

The module limits `MAX_OUTPUT_TOKENS`, response bytes and case count, and rejects `thinking`/tool calls; [docs/decisions/0008-proposed-deepseek-v4-flash-generation-and-embedding-boundary.md](../../docs/decisions/0008-proposed-deepseek-v4-flash-generation-and-embedding-boundary.md) scopes it to synthetic generation.

#### Remediation

Require an explicit invocation flag and budget, record only safe usage metadata, reject fixture policy markers, and keep the spike disconnected from production extraction, authorization and tools.

#### Verification

Run the four-case and repeated-invocation tests with a mocked provider, assert bounded calls/cost, and confirm malformed or instruction-like fixture content is rejected without side effects.

---

## Threat Coverage Verification

| Threat ID | Finding ID | Status |
|-----------|------------|--------|
| T01.S | FIND-01 | ✅ Covered (FIND-01) |
| T02.E | FIND-01 | ✅ Covered (FIND-01) |
| T03.I | FIND-02 | ✅ Mitigated (FIND-02) |
| T04.D | FIND-03 | ✅ Covered (FIND-03) |
| T05.E | FIND-02 | ✅ Covered (FIND-02) |
| T06.A | FIND-04 | ✅ Covered (FIND-04) |
| T07.S | FIND-05 | ✅ Covered (FIND-05) |
| T08.T | FIND-07 | ✅ Mitigated (FIND-07) |
| T09.I | FIND-07 | ✅ Mitigated (FIND-07) |
| T10.D | FIND-06 | ✅ Covered (FIND-06) |
| T11.E | FIND-05 | ✅ Covered (FIND-05) |
| T12.T | FIND-08 | ✅ Covered (FIND-08) |
| T13.I | FIND-09 | ✅ Covered (FIND-09) |
| T14.D | FIND-10 | ✅ Mitigated (FIND-10) |
| T15.A | FIND-08 | ✅ Covered (FIND-08) |
| T16.I | FIND-11 | ✅ Covered (FIND-11) |
| T17.T | FIND-11 | ✅ Covered (FIND-11) |
| T18.D | FIND-12 | ✅ Covered (FIND-12) |
| T19.E | FIND-11 | ✅ Covered (FIND-11) |
| T20.T | FIND-08 | ✅ Mitigated (FIND-08) |
| T21.D | FIND-10 | ✅ Mitigated (FIND-10) |
| T22.I | FIND-09 | ✅ Covered (FIND-09) |
| T23.A | FIND-08 | ✅ Covered (FIND-08) |
| T24.I | FIND-04 | ✅ Covered (FIND-04) |
| T25.T | FIND-04 | ✅ Covered (FIND-04) |
| T26.D | FIND-03 | ✅ Covered (FIND-03) |
| T27.A | FIND-04 | ✅ Mitigated (FIND-04) |
| T28.I | FIND-17 | ✅ Covered (FIND-17) |
| T29.T | FIND-17 | ✅ Covered (FIND-17) |
| T30.D | FIND-18 | ✅ Covered (FIND-18) |
| T31.A | FIND-18 | ✅ Mitigated (FIND-18) |
| T32.T | FIND-13 | ✅ Covered (FIND-13) |
| T33.I | FIND-14 | ✅ Mitigated (FIND-14) |
| T34.D | FIND-15 | ✅ Covered (FIND-15) |
| T35.A | FIND-16 | ✅ Mitigated (FIND-16) |
