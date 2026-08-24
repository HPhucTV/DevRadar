# ADR-025: Accept explicit localhost no-login mode

## Status

Accepted

## Date

2026-08-24

## Context

DevRadar is a single-operator portfolio application on the owner's machine. Session authentication from ADR-015 is required for protected/public deployment, but a login form adds friction when the whole service binds to loopback and the same operator owns every local resource.

Simply setting `DEVRADAR_AUTH_ENABLED=false` cannot grant access: today that state deliberately rejects authenticated resources. Treating every auth-disabled deployment as trusted would also create a dangerous fail-open path if an operator misconfigured a protected/public host.

Custom Sources, ResumeProfile, JobMatch and alerts still require one stable owner subject even when no login form is shown. The design must preserve owner foreign keys/hashes and must not turn a missing session into anonymous cross-owner access.

## Decision

Add explicit `DEVRADAR_LOCAL_NO_LOGIN_ENABLED`, defaulting to false.

- It is valid only with `DEVRADAR_DEPLOYMENT_CLASS=LOCALHOST_SERVICE` and `DEVRADAR_AUTH_ENABLED=false`.
- Enabling it on `PROTECTED` or `PUBLIC`, or together with session auth, fails startup.
- Local owner/operator dependencies resolve one idempotently persisted PostgreSQL `local-operator` subject instead of a session.
- No password, session token or implicit login cookie is created.
- Owner-scoped rows continue to use that subject; no anonymous/null owner is introduced.
- Browser mutations keep Origin allow-list, JSON request, feature gate and rate-limit boundaries. Session CSRF remains mandatory whenever ADR-015 auth is enabled.
- The web app hides login/logout in local no-login mode and redirects `/login` to the dashboard.
- Authentication code, auth tables and migrations remain available for protected/public deployment.

This ADR qualifies ADR-015 for an explicit loopback-only mode; it does not supersede session authentication outside localhost.

## Alternatives considered

### Remove authentication entirely

- Pros: smallest visible UI and fewer runtime concepts.
- Cons: destroys the accepted public security boundary, owner isolation, role enforcement and migration history.
- Rejected: local convenience does not justify making protected/public deployment fail-open.

### Auto-create a hidden session

- Pros: reuses existing session dependencies unchanged.
- Cons: requires implicit credential/session lifecycle, CSRF token propagation and cookie state despite the user choosing no login.
- Rejected: more complex and less truthful than an explicit local identity mode.

### Infer trust whenever auth is disabled

- Pros: no new flag.
- Cons: a typo or missing environment variable silently grants local-operator rights; deployment intent is ambiguous.
- Rejected: authorization must be opt-in and fail-closed.

## Consequences

- Local setup becomes one-click after explicit environment configuration.
- Security configuration and auth dependencies need negative tests for every deployment-class combination.
- A singleton local operator remains in PostgreSQL and owns local resources across restarts while the named volume is retained.
- Public/protected docs and tests must continue to prove login, session, CSRF and role enforcement.
- Local no-login is not a multi-user feature and must never be marketed as public authentication.

## Related decisions

- [ADR-015](0015-accept-v6-authentication-strategy.md): session authentication remains required outside localhost.
- [ADR-024](0024-accept-local-custom-source-profiles-without-bypass.md): custom source safety and no-bypass boundaries remain unchanged.
