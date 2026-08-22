# STRIDE + Abuse Cases — Threat Analysis

> This analysis uses standard STRIDE (Spoofing, Tampering, Repudiation, Information Disclosure, Denial of Service, Elevation of Privilege) extended with Abuse Cases. The A column represents Abuse, not authorization.

## Exploitability Tiers

| Tier | Label | Prerequisites | Assignment Rule |
|------|-------|---------------|----------------|
| **Tier 1** | Direct Exposure | None | Unauthenticated external attacker with no prior access. |
| **Tier 2** | Conditional Risk | Authenticated User, Privileged User, Internal Network, or Local Process Access | Exactly one prerequisite. |
| **Tier 3** | Defense-in-Depth | Host/OS Access, Admin Credentials, component compromise, or multiple prerequisites | Prior breach or infrastructure access. |

## Summary

| Component | Link | S | T | R | I | D | E | A | Total | T1 | T2 | T3 | Risk |
|-----------|------|---|---|---|---|---|---|---|-------|----|----|----|------|
| FastAPI | [Link](#fastapi) | 1 | 0 | 0 | 1 | 1 | 2 | 1 | 6 | 0 | 6 | 0 | High |
| Browser | [Link](#browser) | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | Low |
| NextJS | [Link](#nextjs) | 1 | 1 | 0 | 1 | 1 | 1 | 0 | 5 | 0 | 5 | 0 | High |
| CLI | [Link](#cli) | 0 | 1 | 0 | 1 | 1 | 0 | 1 | 4 | 0 | 0 | 4 | Moderate |
| PostgreSQL | [Link](#postgresql) | 0 | 1 | 0 | 1 | 1 | 1 | 0 | 4 | 0 | 0 | 4 | High |
| FastEmbed | [Link](#fastembed) | 0 | 1 | 0 | 1 | 1 | 0 | 1 | 4 | 0 | 0 | 4 | Moderate |
| ApprovedSources | [Link](#approvedsources) | 0 | 1 | 0 | 1 | 1 | 0 | 1 | 4 | 0 | 0 | 4 | Moderate |
| Discord | [Link](#discord) | 0 | 1 | 0 | 1 | 1 | 0 | 1 | 4 | 0 | 0 | 4 | High |
| DeepSeek | [Link](#deepseek) | 0 | 1 | 0 | 1 | 1 | 0 | 1 | 4 | 0 | 0 | 4 | Moderate |
| Operator | [Link](#operator) | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | Low |
| **Totals** | | **2** | **7** | **0** | **8** | **8** | **4** | **6** | **35** | **0** | **11** | **24** | |

---

## FastAPI

**Trust Boundary:** Application
**Role:** REST API, protected local resources, matching and alert dispatch.
**Data Flows:** DF02, DF03, DF04, DF09
**Pod Co-location:** N/A

### STRIDE-A Analysis

#### Tier 1 — Direct Exposure (No Prerequisites)

| ID | Category | Threat | Prerequisites | Affected Flow | Mitigation | Status |
|----|----------|--------|---------------|---------------|------------|--------|
*No Tier 1 threats identified.*

#### Tier 2 — Conditional Risk

| ID | Category | Threat | Prerequisites | Affected Flow | Mitigation | Status |
|----|----------|--------|---------------|---------------|------------|--------|
| T01.S | Spoofing | Local owner token can stand in for production identity on V5 protected routes. | Local Process Access | DF02 | V6 auth must replace owner header. | Open |
| T02.E | Elevation of Privilege | Operator write gates are environment flags, not authenticated roles. | Local Process Access | DF02 | Keep gates off and add server-side roles before exposure. | Open |
| T03.I | Information Disclosure | A future route could return owner/profile data without a durable auth policy. | Local Process Access | DF02 | Generic 404, response allow-lists and V6 authorization ADR. | Mitigated |
| T04.D | Denial of Service | Synchronous alert/provider work can consume API capacity. | Local Process Access | DF09 | maxItems and bounded connector retries. | Open |
| T05.E | Elevation of Privilege | Cross-owner access is possible if a new route forgets the owner predicate. | Local Process Access | DF02 | Shared owner dependency and contract tests. | Open |
| T06.A | Abuse | Repeated local dispatch can amplify webhook traffic and provider cost. | Local Process Access | DF09 | Unique delivery key, local gate and bounded dispatch. | Open |

#### Tier 3 — Defense-in-Depth

| ID | Category | Threat | Prerequisites | Affected Flow | Mitigation | Status |
|----|----------|--------|---------------|---------------|------------|--------|
*No Tier 3 threats identified.*

#### Categories Not Applicable

| Category | Justification |
|----------|---------------|
| Repudiation | Structured events provide correlation but no public audit identity yet. |

## NextJS

**Trust Boundary:** Application
**Role:** Dashboard and same-origin BFF forwarding protected requests.
**Data Flows:** DF01, DF02
**Pod Co-location:** N/A

### STRIDE-A Analysis

#### Tier 1 — Direct Exposure (No Prerequisites)

| ID | Category | Threat | Prerequisites | Affected Flow | Mitigation | Status |
|----|----------|--------|---------------|---------------|------------|--------|
*No Tier 1 threats identified.*

#### Tier 2 — Conditional Risk

| ID | Category | Threat | Prerequisites | Affected Flow | Mitigation | Status |
|----|----------|--------|---------------|---------------|------------|--------|
| T07.S | Spoofing | Browser-memory owner token can be replayed by a same-host script or copied local session. | Local Process Access | DF01 | No persistence, no logs, V6 authenticated session. | Open |
| T08.T | Tampering | BFF accepts JSON and relies on FastAPI schema for field policy. | Local Process Access | DF01 | Backend extra-forbid and bounded route parsing. | Mitigated |
| T09.I | Information Disclosure | Client rendering could surface owner hash, raw CV or provider body. | Local Process Access | DF01 | Typed sanitized contracts and source tests. | Mitigated |
| T10.D | Denial of Service | No rate limiter exists on BFF requests before V6. | Local Process Access | DF01 | Loopback binding and small request bodies only. | Open |
| T11.E | Elevation of Privilege | Same-origin proxy is not an authorization boundary by itself. | Local Process Access | DF02 | FastAPI remains authoritative; public auth deferred. | Open |

#### Tier 3 — Defense-in-Depth

| ID | Category | Threat | Prerequisites | Affected Flow | Mitigation | Status |
|----|----------|--------|---------------|---------------|------------|--------|
*No Tier 3 threats identified.*

#### Categories Not Applicable

| Category | Justification |
|----------|---------------|
| Repudiation | No client-owned audit trail or public identity is present. |
| Abuse | UI actions are bounded and backend rules remain authoritative. |

## CLI

**Trust Boundary:** CrawlerSandbox
**Role:** Approved ingestion and one-shot worker entrypoint.
**Data Flows:** DF05, DF06, DF07, DF08
**Pod Co-location:** N/A

### STRIDE-A Analysis

#### Tier 1 — Direct Exposure (No Prerequisites)

| ID | Category | Threat | Prerequisites | Affected Flow | Mitigation | Status |
|----|----------|--------|---------------|---------------|------------|--------|
*No Tier 1 threats identified.*

#### Tier 2 — Conditional Risk

| ID | Category | Threat | Prerequisites | Affected Flow | Mitigation | Status |
|----|----------|--------|---------------|---------------|------------|--------|
*No Tier 2 threats identified.*

#### Tier 3 — Defense-in-Depth

| ID | Category | Threat | Prerequisites | Affected Flow | Mitigation | Status |
|----|----------|--------|---------------|---------------|------------|--------|
| T12.T | Tampering | Crawler configuration or source registry could drift from approved allow-list. | Host/OS Access | DF06 | Immutable typed registry and source/config equality checks. | Open |
| T13.I | Information Disclosure | Raw snapshots and crawl artifacts may expose public-source content if host storage is compromised. | Host/OS Access | DF07 | Retention, redaction and protected volumes. | Open |
| T14.D | Denial of Service | Browser/source response can exhaust crawler resources despite current bounds. | Host/OS Access | DF06 | Page/byte/time/browser sandbox budgets. | Mitigated |
| T15.A | Abuse | Operator can run a source more often than its policy allows. | Host/OS Access | DF05 | Rate policy, operator gate and audit events. | Open |

#### Categories Not Applicable

| Category | Justification |
|----------|---------------|
| Spoofing | CLI has no network listener and runs under local operator account. |
| Repudiation | Run IDs and summaries provide bounded correlation. |
| Elevation of Privilege | Container drops capabilities and uses non-root crawler profile. |

## PostgreSQL

**Trust Boundary:** Application
**Role:** Authoritative relational/vector persistence.
**Data Flows:** DF03, DF07
**Pod Co-location:** N/A

### STRIDE-A Analysis

#### Tier 1 — Direct Exposure (No Prerequisites)

| ID | Category | Threat | Prerequisites | Affected Flow | Mitigation | Status |
|----|----------|--------|---------------|---------------|------------|--------|
*No Tier 1 threats identified.*

#### Tier 2 — Conditional Risk

| ID | Category | Threat | Prerequisites | Affected Flow | Mitigation | Status |
|----|----------|--------|---------------|---------------|------------|--------|
*No Tier 2 threats identified.*

#### Tier 3 — Defense-in-Depth

| ID | Category | Threat | Prerequisites | Affected Flow | Mitigation | Status |
|----|----------|--------|---------------|---------------|------------|--------|
| T16.I | Information Disclosure | Compose exposes a local default database password and owner-derived artifacts depend on deployment hygiene. | Host/OS Access | DF03 | Use managed secret and least privilege in V6. | Open |
| T17.T | Tampering | Database role and migration privilege scope is not separately proven for public deployment. | Host/OS Access | DF03 | Dedicated role, migration job and network policy. | Open |
| T18.D | Denial of Service | Raw/job/profile retention can increase storage and query pressure over time. | Host/OS Access | DF03 | Retention jobs, indexes and measured capacity gates. | Open |
| T19.E | Elevation of Privilege | DB compromise bypasses owner predicates and exposes CV/match records. | Host/OS Access | DF03 | Network isolation, least privilege, encryption and authz. | Open |

#### Categories Not Applicable

| Category | Justification |
|----------|---------------|
| Spoofing | Database is not directly exposed on the host network. |
| Repudiation | DB timestamps and event IDs are evidence but not a signed audit trail. |
| Abuse | Business-rule abuse is owned by FastAPI. |

## FastEmbed

**Trust Boundary:** Application
**Role:** Fixed local embedding artifact and inference call.
**Data Flows:** DF04
**Pod Co-location:** N/A

### STRIDE-A Analysis

#### Tier 1 — Direct Exposure (No Prerequisites)

| ID | Category | Threat | Prerequisites | Affected Flow | Mitigation | Status |
|----|----------|--------|---------------|---------------|------------|--------|
*No Tier 1 threats identified.*

#### Tier 2 — Conditional Risk

| ID | Category | Threat | Prerequisites | Affected Flow | Mitigation | Status |
|----|----------|--------|---------------|---------------|------------|--------|
*No Tier 2 threats identified.*

#### Tier 3 — Defense-in-Depth

| ID | Category | Threat | Prerequisites | Affected Flow | Mitigation | Status |
|----|----------|--------|---------------|---------------|------------|--------|
| T32.T | Tampering | Local model artifact or revision can be replaced before startup. | Host/OS Access | DF04 | Fixed revision/SHA-256 and image pinning. | Open |
| T33.I | Information Disclosure | Inference runtime could emit telemetry or externalize profile/job text. | Host/OS Access | DF04 | ORT_DISABLE_TELEMETRY=1, local-files-only and no raw logs. | Mitigated |
| T34.D | Denial of Service | Crafted profile/query can increase local inference CPU/memory. | Host/OS Access | DF04 | Bounded input and container resource limits before public exposure. | Open |
| T35.A | Abuse | Stale model/input identity can produce misleading match ranking. | Host/OS Access | DF04 | Current hash/model identity joins and stale filtering. | Mitigated |

#### Categories Not Applicable

| Category | Justification |
|----------|---------------|
| Spoofing | In-process artifact has no identity protocol. |
| Repudiation | Inference is correlated by API event, not independently signed. |
| Elevation of Privilege | Model output is not authorized to select tools or policy. |

## ApprovedSources

**Trust Boundary:** External
**Role:** Untrusted third-party job content fetched only through approved adapters.
**Data Flows:** DF06
**Pod Co-location:** N/A

### STRIDE-A Analysis

#### Tier 1 — Direct Exposure (No Prerequisites)

| ID | Category | Threat | Prerequisites | Affected Flow | Mitigation | Status |
|----|----------|--------|---------------|---------------|------------|--------|
*No Tier 1 threats identified.*

#### Tier 2 — Conditional Risk

| ID | Category | Threat | Prerequisites | Affected Flow | Mitigation | Status |
|----|----------|--------|---------------|---------------|------------|--------|
*No Tier 2 threats identified.*

#### Tier 3 — Defense-in-Depth

| ID | Category | Threat | Prerequisites | Affected Flow | Mitigation | Status |
|----|----------|--------|---------------|---------------|------------|--------|
| T20.T | Tampering | Source response can contain prompt injection or malformed fields that try to alter parser policy. | Host/OS Access | DF06 | Treat HTML/JD as untrusted; deterministic validation and default-deny tools. | Mitigated |
| T21.D | Denial of Service | Approved source can become slow, rate-limited or return oversized payloads. | Host/OS Access | DF06 | Timeouts, size caps, retry/quarantine and coverage gates. | Mitigated |
| T22.I | Information Disclosure | Source response can include unexpected personal/contact data in raw snapshots. | Host/OS Access | DF06 | Source scope, redaction and raw retention policy. | Open |
| T23.A | Abuse | Continuing to crawl after terms/robots policy changes can violate source constraints. | Host/OS Access | DF06 | Approval record, quarantine and operator review. | Open |

#### Categories Not Applicable

| Category | Justification |
|----------|---------------|
| Spoofing | Source identity is checked against registry host/config, not user identity. |
| Repudiation | Third-party source does not provide signed provenance. |
| Elevation of Privilege | Source content cannot grant application permissions. |

## Discord

**Trust Boundary:** External
**Role:** One operator-owned notification endpoint.
**Data Flows:** DF09
**Pod Co-location:** N/A

### STRIDE-A Analysis

#### Tier 1 — Direct Exposure (No Prerequisites)

| ID | Category | Threat | Prerequisites | Affected Flow | Mitigation | Status |
|----|----------|--------|---------------|---------------|------------|--------|
*No Tier 1 threats identified.*

#### Tier 2 — Conditional Risk

| ID | Category | Threat | Prerequisites | Affected Flow | Mitigation | Status |
|----|----------|--------|---------------|---------------|------------|--------|
*No Tier 2 threats identified.*

#### Tier 3 — Defense-in-Depth

| ID | Category | Threat | Prerequisites | Affected Flow | Mitigation | Status |
|----|----------|--------|---------------|---------------|------------|--------|
| T24.I | Information Disclosure | Webhook URL/token in process environment can be exposed through host/process compromise. | Host/OS Access | DF09 | Never persist/log URL; V6 managed secret rotation. | Open |
| T25.T | Tampering | Discord has no native idempotency contract; crash after acceptance can replay a message. | Host/OS Access | DF09 | DB unique key/status and explicit crash-window documentation. | Open |
| T26.D | Denial of Service | Synchronous connector retry can occupy an API request during provider outage. | Host/OS Access | DF09 | Three attempts, timeout and maxItems bound. | Open |
| T27.A | Abuse | A local rule can notify repeatedly across changing job hashes or repeated dispatch calls. | Host/OS Access | DF09 | Rule gate, bounded dispatch and hash-based delivery identity. | Mitigated |

#### Categories Not Applicable

| Category | Justification |
|----------|---------------|
| Spoofing | Provider identity is pinned by URL host, not an inbound login. |
| Repudiation | Provider receipt is not a signed application audit record. |
| Elevation of Privilege | Discord cannot grant DevRadar permissions. |

## DeepSeek

**Trust Boundary:** External
**Role:** Optional synthetic-only provider spike.
**Data Flows:** DF08
**Pod Co-location:** N/A

### STRIDE-A Analysis

#### Tier 1 — Direct Exposure (No Prerequisites)

| ID | Category | Threat | Prerequisites | Affected Flow | Mitigation | Status |
|----|----------|--------|---------------|---------------|------------|--------|
*No Tier 1 threats identified.*

#### Tier 2 — Conditional Risk

| ID | Category | Threat | Prerequisites | Affected Flow | Mitigation | Status |
|----|----------|--------|---------------|---------------|------------|--------|
*No Tier 2 threats identified.*

#### Tier 3 — Defense-in-Depth

| ID | Category | Threat | Prerequisites | Affected Flow | Mitigation | Status |
|----|----------|--------|---------------|---------------|------------|--------|
| T28.I | Information Disclosure | DeepSeek API key or synthetic prompt could be exposed by host/process compromise. | Host/OS Access | DF08 | .env.local only, rotation and synthetic-only contract. | Open |
| T29.T | Tampering | A future caller could accidentally send real JD/CV content across the synthetic boundary. | Host/OS Access | DF08 | Fail-closed spike schema and ADR-008 scope. | Open |
| T30.D | Denial of Service | Repeated spike calls can consume provider quota or budget. | Host/OS Access | DF08 | Four-case bounded run and opt-in invocation. | Open |
| T31.A | Abuse | Prompt injection in synthetic fixtures could be mistaken for policy-bearing model output. | Host/OS Access | DF08 | No production caller, schema/evidence validator and no tool execution. | Mitigated |

#### Categories Not Applicable

| Category | Justification |
|----------|---------------|
| Spoofing | No inbound provider authentication path exists in DevRadar. |
| Repudiation | Spike audit metadata is local and not provider attestation. |
| Elevation of Privilege | Provider output cannot select tools or mutate policy. |

## Browser

**Trust Boundary:** External
**Role:** Local browser user agent rendering the dashboard and BFF responses.
**Data Flows:** DF01
**Pod Co-location:** N/A

### STRIDE-A Analysis

#### Tier 1 — Direct Exposure (No Prerequisites)

| ID | Category | Threat | Prerequisites | Affected Flow | Mitigation | Status |
|----|----------|--------|---------------|---------------|------------|--------|
*No Tier 1 threats identified.*

#### Tier 2 — Conditional Risk

| ID | Category | Threat | Prerequisites | Affected Flow | Mitigation | Status |
|----|----------|--------|---------------|---------------|------------|--------|
*No Tier 2 threats identified.*

#### Tier 3 — Defense-in-Depth

| ID | Category | Threat | Prerequisites | Affected Flow | Mitigation | Status |
|----|----------|--------|---------------|---------------|------------|--------|
*No Tier 3 threats identified.*

#### Categories Not Applicable

| Category | Justification |
|----------|---------------|
| Spoofing | The browser is an external user agent, not an identity authority. |
| Tampering | Server-side schemas remain authoritative for all mutations. |
| Repudiation | Browser actions are correlated by server request IDs, not client claims. |
| Information Disclosure | Response filtering is owned by NextJS and FastAPI. |
| Denial of Service | Browser has no server-side listener or privileged resource authority. |
| Elevation of Privilege | Browser cannot grant itself server roles. |
| Abuse | Business rules and rate limits are enforced on the server. |

## Operator

**Trust Boundary:** External
**Role:** Single human operator controlling local runs and secrets.
**Data Flows:** DF05
**Pod Co-location:** N/A

### STRIDE-A Analysis

#### Tier 1 — Direct Exposure (No Prerequisites)

| ID | Category | Threat | Prerequisites | Affected Flow | Mitigation | Status |
|----|----------|--------|---------------|---------------|------------|--------|
*No Tier 1 threats identified.*

#### Tier 2 — Conditional Risk

| ID | Category | Threat | Prerequisites | Affected Flow | Mitigation | Status |
|----|----------|--------|---------------|---------------|------------|--------|
*No Tier 2 threats identified.*

#### Tier 3 — Defense-in-Depth

| ID | Category | Threat | Prerequisites | Affected Flow | Mitigation | Status |
|----|----------|--------|---------------|---------------|------------|--------|
*No Tier 3 threats identified.*

#### Categories Not Applicable

| Category | Justification |
|----------|---------------|
| Spoofing | The operator is the trusted local actor, not an inbound protocol. |
| Tampering | CLI and source registry validate operator-supplied configuration. |
| Repudiation | CrawlRun IDs and structured events provide bounded correlation. |
| Information Disclosure | Secret handling and raw-data policy are application boundaries. |
| Denial of Service | Operator has no remote listener authority in the model. |
| Elevation of Privilege | Role enforcement belongs to FastAPI, not the human label. |
| Abuse | Source frequency and dispatch policy are enforced by deterministic workflows. |
