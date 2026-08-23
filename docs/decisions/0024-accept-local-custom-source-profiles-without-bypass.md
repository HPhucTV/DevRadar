# ADR-024: Accept local custom source profiles without access-control bypass

## Status

Accepted

## Date

2026-08-23

## Context

The static approved-source registry is correct for reproducible public ingestion, but a single operator also needs to monitor additional websites chosen for personal use. A public endpoint that accepts arbitrary URLs would create an SSRF/fetch proxy and would blur the distinction between a source that passed the project approval gate and a source that the owner merely wants to test.

The project must preserve the existing no-bypass boundary. CAPTCHA, authentication, paywall and anti-bot controls may represent access restrictions, contractual conditions or security controls. A user assertion that a source is for personal use is not equivalent to permission from the source owner.

## Decision

Add a separate local/protected `CustomSourceProfile` capability:

- owner creates a profile with an HTTPS base URL, host/path boundary, parser mapping and deterministic schedule;
- profile is labeled `owner_authorized_local`, distinct from global `approved` sources;
- hybrid deterministic parser supports JSON/JSON-LD, HTML and explicit owner field mappings;
- preview must succeed before schedule enablement;
- custom runs reuse existing bounded fetch, snapshot, normalization, deduplication, change detection and health contracts;
- feature is enabled only when `DEVRADAR_CUSTOM_SOURCES_LOCAL_ENABLED=true` and requests are authenticated/owner-scoped;
- redirects, DNS results, response/page/time budgets and rate limits remain fail-closed;
- `401`, `403`, CAPTCHA, paywall and anti-bot challenge results move the profile to a blocked/permission-required state and are never bypassed or automatically retried;
- custom profiles are not exposed through public onboarding and do not create Vietnam market claims without cohort evidence.

The detailed contract is recorded in [Custom Source Profile design](../superpowers/specs/2026-08-23-custom-source-profile-design.md).

## Alternatives considered

### Keep only the static approved registry

- Pros: smallest attack surface and simplest reproducibility.
- Cons: does not satisfy the owner's need to monitor a personally selected source.
- Rejected for the local/protected use case.

### Public arbitrary-URL crawler proxy

- Pros: maximum flexibility with minimal source configuration.
- Cons: SSRF, private-network access, abuse amplification, unclear source permission, secret leakage and no stable parser/provenance contract.
- Rejected.

### One-shot URL import only

- Pros: smaller lifecycle and lower blast radius.
- Cons: no recurring schedule, source health or change detection.
- Deferred as a possible preview primitive; the accepted capability is the bounded custom profile.

## Consequences

- New profile persistence, API/BFF, schedule and UI contracts require migrations, owner authorization, negative tests and documentation updates before implementation.
- The source registry and public `approved` semantics remain unchanged.
- Custom profiles need a parser preview and may require source-specific mapping; generic auto-detection is not guaranteed to work for every site.
- Website permission remains an operator responsibility; the application records an acknowledgement but does not certify legal authorization.
- No credential/cookie storage or browser-profile reuse is introduced by this decision.
