# Security Assessment

---

## Report Files

| File | Description |
|------|-------------|
| [0-assessment.md](0-assessment.md) | This document — executive summary, risk rating, action plan, metadata |
| [0.1-architecture.md](0.1-architecture.md) | Architecture overview, components, scenarios, tech stack |
| [1-threatmodel.md](1-threatmodel.md) | Threat model DFD diagram with element, flow, and boundary tables |
| [1.1-threatmodel.mmd](1.1-threatmodel.mmd) | Pure Mermaid DFD source file |
| [2-stride-analysis.md](2-stride-analysis.md) | Full STRIDE-A analysis for all components |
| [3-findings.md](3-findings.md) | Prioritized security findings with remediation |
| [threat-inventory.json](threat-inventory.json) | Deterministic machine-readable inventory for future comparison |

---

## Executive Summary

DevRadar is a modular-monolith job intelligence platform running on one operator workstation. The current Compose topology binds the API, Next.js dashboard and PostgreSQL to loopback; the crawler is an optional non-root sandbox and outbound providers are allow-listed or synthetic-only.

The assessment covers the current V5 closeout and the V6 public-exposure boundary. No Tier 1 threat is supported by the deployment evidence, but temporary owner-header gates, synchronous local work, host-held secrets, raw retention and future public deployment assumptions require explicit V6 controls before any internet-facing release.

The analysis covers 10 system elements across 3 trust boundaries.

### Risk Rating: Elevated

The rating is Elevated because the present service is not publicly reachable, yet the current identity mechanism is not production authentication and several sensitive capabilities would become high-impact if loopback binding, deployment secrets or owner predicates were changed without a corresponding control. Existing bounded parsing, allow-lists, local embeddings and redacted responses reduce immediate likelihood but do not replace authentication, rate limiting, retention or deployment gates.

> **Note on threat counts:** This analysis identified 35 threats across 8 analyzed process/service components. This count reflects comprehensive STRIDE-A coverage, not systemic insecurity. Of these, **0 are directly exploitable** without prerequisites (Tier 1). The remaining 11 Tier 2 and 24 Tier 3 threats represent conditional risks and defense-in-depth considerations.

---

## Action Summary

| Tier | Description | Threats | Findings | Priority |
|------|-------------|---------|----------|----------|
| [Tier 1](3-findings.md#tier-1--direct-exposure-no-prerequisites) | Directly exploitable | 0 | 0 | 🔴 Critical Risk |
| [Tier 2](3-findings.md#tier-2--conditional-risk-authenticated--single-prerequisite) | Requires a single local prerequisite | 11 | 6 | 🟠 Elevated Risk |
| [Tier 3](3-findings.md#tier-3--defense-in-depth-prior-compromise--host-access) | Requires prior compromise | 24 | 12 | 🟡 Moderate Risk |
| **Total** | | **35** | **18** | |

### Priority by Tier and CVSS Score (Top 10)

| Finding | Tier | CVSS Score | SDL Severity | Title |
|---------|------|------------|-------------|-------|
| [FIND-01](3-findings.md#find-01-local-owner-header-is-not-production-authentication) | T2 | 7.1 | Important | Local owner header is not production authentication |
| [FIND-02](3-findings.md#find-02-owner-predicate-coverage-can-regress-across-new-routes) | T2 | 6.3 | Important | Owner predicate coverage can regress across new routes |
| [FIND-03](3-findings.md#find-03-synchronous-alert-work-has-no-request-rate-limit) | T2 | 5.3 | Moderate | Synchronous alert work has no request rate limit |
| [FIND-05](3-findings.md#find-05-same-origin-bff-forwarding-is-not-an-authorization-boundary) | T2 | 5.1 | Moderate | Same-origin BFF forwarding is not an authorization boundary |
| [FIND-07](3-findings.md#find-07-response-contracts-could-regress-into-profile-or-provider-disclosure) | T2 | 5.0 | Moderate | Response contracts could regress into profile or provider disclosure |
| [FIND-06](3-findings.md#find-06-bff-requests-lack-a-route-level-rate-and-body-budget) | T2 | 4.7 | Moderate | BFF requests lack a route-level rate and body budget |
| [FIND-08](3-findings.md#find-08-crawler-allow-list-and-source-policy-can-drift) | T3 | 6.8 | Important | Crawler allow-list and source policy can drift |
| [FIND-11](3-findings.md#find-11-local-database-defaults-and-broad-migration-privileges-are-unsafe-for-deployment) | T3 | 6.7 | Important | Local database defaults and broad migration privileges are unsafe for deployment |
| [FIND-09](3-findings.md#find-09-raw-snapshots-and-unexpected-source-pii-depend-on-host-retention-hygiene) | T3 | 6.0 | Important | Raw snapshots and unexpected source PII depend on host retention hygiene |
| [FIND-10](3-findings.md#find-10-crawlerbrowser-resource-budgets-can-be-exhausted-by-hostile-responses) | T3 | 6.0 | Important | Crawler/browser resource budgets can be exhausted by hostile responses |

### Quick Wins

| Finding | Title | Why Quick |
|---------|-------|-----------|
| [FIND-06](3-findings.md#find-06-bff-requests-lack-a-route-level-rate-and-body-budget) | BFF requests lack a route-level rate and body budget | Add a small route budget and upstream timeout before public exposure. |
| [FIND-14](3-findings.md#find-14-embedding-runtime-telemetry-could-disclose-private-text) | Embedding runtime telemetry could disclose private text | Keep the already-defined telemetry-off/local-only controls as a release gate. |
| [FIND-16](3-findings.md#find-16-stale-modelinput-identity-can-corrupt-match-interpretation) | Stale model/input identity can corrupt match interpretation | Turn existing identity joins into a mandatory negative regression fixture. |
| [FIND-18](3-findings.md#find-18-deepseek-spike-can-consume-quota-or-treat-fixture-text-as-policy) | DeepSeek spike can consume quota or treat fixture text as policy | Preserve the four-case opt-in budget and add one malformed-fixture assertion. |

---

## Analysis Context & Assumptions

### Analysis Scope

| Constraint | Description |
|------------|-------------|
| Scope | Current `main` HEAD `e1e2b8a`, V5 closeout runtime, Compose topology and V6 public-exposure/auth boundary. |
| Excluded | No internet-wide scan, live provider abuse, secret-value inspection, browser exploit execution or public deployment claim. |
| Focus Areas | Identity/authorization, loopback exposure, source ingestion, CV privacy, provider secrets, persistence integrity, resource exhaustion and supply-chain boundaries. |

### Infrastructure Context

| Category | Discovered from Codebase | Findings Affected |
|----------|--------------------------|-------------------|
| Loopback service | [compose.yaml](../../compose.yaml), [web/package.json](../../web/package.json) bind API, web and database to loopback | FIND-01–FIND-07, FIND-11 |
| Container hardening | [compose.yaml](../../compose.yaml) uses read-only API, dropped capabilities and crawler seccomp | FIND-08, FIND-10 |
| PostgreSQL system of record | [src/devradar/platform/database.py](../../src/devradar/platform/database.py), [migrations](../../migrations) | FIND-09, FIND-11, FIND-12 |
| Local embedding boundary | [src/devradar/intelligence/embeddings.py](../../src/devradar/intelligence/embeddings.py) pins revision and disables telemetry | FIND-13–FIND-16 |
| Synthetic provider spike | [src/devradar/intelligence/deepseek_spike.py](../../src/devradar/intelligence/deepseek_spike.py), [ADR-008](../../docs/decisions/0008-proposed-deepseek-v4-flash-generation-and-embedding-boundary.md) | FIND-17, FIND-18 |

### Needs Verification

| Item | Question | What to Check | Why Uncertain |
|------|----------|---------------|---------------|
| Public ingress | Will a reverse proxy or cloud load balancer be introduced for V6? | Rendered deployment manifests, TLS and network policy | Current repository has only loopback Compose bindings. |
| Auth session store | Where will revocation/session state live? | ADR-015 implementation design and migration test | V6-001 records the strategy boundary; no runtime auth exists yet. |
| Secret management | Can database, Discord and provider secrets rotate without rebuild? | Deployment secret manager and rotation drill | `.env.example` is intentionally local-only. |
| Retention/restore | What are raw snapshot/CV retention periods and restore RPO/RTO? | Automated purge and restore evidence | Operations docs define a gate but no production drill exists. |
| Egress policy | Can crawler and embedding containers reach only their approved destinations? | Network-level deny/allow test | Application-level URL policy is proven; network egress is not. |

### Finding Overrides

| Finding ID | Original Severity | Override | Justification | New Status |
|------------|-------------------|----------|---------------|------------|
| — | — | — | No overrides applied. Update this section after review. | — |

### Additional Notes

The localhost classification is binding for this report: no finding uses `None` prerequisites, no Tier 1 finding is created, and no `AV:N` vector is used for a non-external component. Public release remains out of scope until V6-002 through V6-007 provide evidence.

---

## References Consulted

### Security Standards

| Standard | URL | How Used |
|----------|-----|----------|
| Microsoft SDL Bug Bar | https://www.microsoft.com/en-us/msrc/sdlbugbar | Severity classification |
| OWASP Top 10:2025 | https://owasp.org/Top10/2025/ | Threat categorization |
| CVSS 4.0 | https://www.first.org/cvss/v4.0/specification-document | Risk scoring |
| CWE | https://cwe.mitre.org/ | Weakness classification |
| STRIDE | https://learn.microsoft.com/en-us/azure/security/develop/threat-modeling-tool-threats | Threat enumeration |

### Component Documentation

| Component | Documentation URL | Relevant Section |
|-----------|------------------|------------------|
| FastAPI | https://fastapi.tiangolo.com/ | Dependencies, OpenAPI and middleware boundaries |
| Next.js | https://nextjs.org/docs | App Router and route-handler deployment |
| PostgreSQL | https://www.postgresql.org/docs/current/ | Roles, privileges and data retention controls |
| Docker Compose | https://docs.docker.com/compose/ | Bindings, read-only filesystem and capabilities |
| Playwright | https://playwright.dev/python/docs/docker | Browser sandbox and container hardening |
| Discord Webhooks | https://discord.com/developers/docs/resources/webhook | Webhook delivery contract and limits |
| DeepSeek API | https://api-docs.deepseek.com/ | Synthetic spike provider boundary |

---

## Report Metadata

| Field | Value |
|-------|-------|
| Source Location | `C:\Users\PC\Documents\Duy\DevRadar` |
| Git Repository | `https://github.com/HPhucTV/DevRadar.git` |
| Git Branch | `main` |
| Git Commit | `e1e2b8a` (`2026-08-23 03:21:50 +0700`) |
| Model | `GPT-5 (Codex)` |
| Machine Name | `LAPTOP-A07DUJIR` |
| Analysis Started | `2026-08-22 20:22:57 UTC` |
| Analysis Completed | `2026-08-22 20:49:04 UTC` |
| Duration | `26m 7s` |
| Output Folder | `docs/threat-model-20260822-202257` |
| Prompt | `Threat model public exposure và auth ADR cho V6-001` |

---

## Classification Reference

| Classification | Values |
|---------------|--------|
| **Exploitability Tiers** | **T1** Direct Exposure (no prerequisites) · **T2** Conditional Risk (single prerequisite) · **T3** Defense-in-Depth (multiple prerequisites or infrastructure access) |
| **STRIDE + Abuse** | **S** Spoofing · **T** Tampering · **R** Repudiation · **I** Information Disclosure · **D** Denial of Service · **E** Elevation of Privilege · **A** Abuse (feature misuse) |
| **SDL Severity** | `Critical` · `Important` · `Moderate` · `Low` |
| **Remediation Effort** | `Low` · `Medium` · `High` |
| **Mitigation Type** | `Redesign` · `Standard Mitigation` · `Custom Mitigation` · `Existing Control` · `Accept Risk` · `Transfer Risk` |
| **Threat Status** | `Open` · `Mitigated` · `Platform` |
| **Incremental Tags** | `[Existing]` · `[Fixed]` · `[Partial]` · `[New]` · `[Removed]` (incremental reports only) |
| **CVSS** | CVSS 4.0 vector with `CVSS:4.0/` prefix |
| **CWE** | Hyperlinked CWE ID (e.g., [CWE-306](https://cwe.mitre.org/data/definitions/306.html)) |
| **OWASP** | OWASP Top 10:2025 mapping (e.g., A01:2025 – Broken Access Control) |
