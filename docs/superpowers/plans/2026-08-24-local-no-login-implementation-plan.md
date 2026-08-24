# Local No-Login Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cho phép một operator dùng DevRadar trên loopback mà không cần session login, trong khi protected/public deployment vẫn fail-closed và giữ nguyên ADR-015.

**Architecture:** Thêm một feature gate explicit ở security configuration và một `local-operator` PostgreSQL được tạo idempotently. Các auth dependency trả cùng `AuthContext` cho session mode hoặc local mode; local mutation chỉ bỏ session CSRF nhưng vẫn kiểm Origin. Next.js chỉ ẩn login khi server environment xác nhận local no-login.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy/PostgreSQL, pytest, Next.js 16, React 19, Node test runner, Docker Compose.

---

### Task 1: Khóa ma trận cấu hình local no-login

**Files:**
- Modify: `tests/test_security_config.py`
- Modify: `src/devradar/platform/security_config.py`

- [ ] **Step 1: Viết test fail cho các tổ hợp hợp lệ và bị cấm**

```python
@pytest.mark.parametrize("deployment", ["PROTECTED", "PUBLIC"])
def test_local_no_login_is_rejected_outside_localhost(
    monkeypatch: pytest.MonkeyPatch, deployment: str
) -> None:
    monkeypatch.setenv("DEVRADAR_DEPLOYMENT_CLASS", deployment)
    monkeypatch.setenv("DEVRADAR_LOCAL_NO_LOGIN_ENABLED", "true")
    monkeypatch.setenv("DEVRADAR_AUTH_ENABLED", "false")
    with pytest.raises(SecurityConfigurationError, match="local_no_login_forbidden"):
        validate_security_configuration()


def test_local_no_login_is_rejected_with_session_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEVRADAR_DEPLOYMENT_CLASS", "LOCALHOST_SERVICE")
    monkeypatch.setenv("DEVRADAR_LOCAL_NO_LOGIN_ENABLED", "true")
    monkeypatch.setenv("DEVRADAR_AUTH_ENABLED", "true")
    with pytest.raises(SecurityConfigurationError, match="local_no_login_auth_conflict"):
        validate_security_configuration()
```

- [ ] **Step 2: Chạy test và xác nhận RED**

Run: `.venv\Scripts\python -m pytest tests/test_security_config.py -q`

Expected: FAIL vì `DEVRADAR_LOCAL_NO_LOGIN_ENABLED` chưa được validate.

- [ ] **Step 3: Thêm parser boolean và fail-closed validation**

```python
LOCAL_NO_LOGIN_ENABLED_ENV = "DEVRADAR_LOCAL_NO_LOGIN_ENABLED"


def local_no_login_enabled() -> bool:
    return os.environ.get(LOCAL_NO_LOGIN_ENABLED_ENV, "false").strip().casefold() == "true"


def validate_security_configuration(database_url: str | None = None) -> DeploymentClass:
    deployment = _deployment_class()
    local_no_login = local_no_login_enabled()
    if local_no_login and deployment != "LOCALHOST_SERVICE":
        raise SecurityConfigurationError("local_no_login_forbidden")
    if local_no_login and auth_enabled():
        raise SecurityConfigurationError("local_no_login_auth_conflict")
    # existing custom-source and protected/public checks remain unchanged
```

- [ ] **Step 4: Chạy test và xác nhận GREEN**

Run: `.venv\Scripts\python -m pytest tests/test_security_config.py -q`

Expected: toàn bộ test trong file PASS.

- [ ] **Step 5: Commit cấu hình**

```powershell
git add tests/test_security_config.py src/devradar/platform/security_config.py
git commit -m "feat: gate explicit local no-login mode"
```

### Task 2: Tạo local operator và dùng trong auth dependencies

**Files:**
- Create: `src/devradar/auth/local_operator.py`
- Modify: `src/devradar/auth/dependencies.py`
- Modify: `src/devradar/api/auth.py`
- Modify: `tests/integration/test_auth_api.py`

- [ ] **Step 1: Viết PostgreSQL integration test fail cho singleton identity và local CSRF boundary**

```python
@pytest.mark.postgresql
def test_local_no_login_reuses_operator_without_session(
    fresh_postgresql_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEVRADAR_DATABASE_URL", fresh_postgresql_url)
    monkeypatch.setenv("DEVRADAR_DEPLOYMENT_CLASS", "LOCALHOST_SERVICE")
    monkeypatch.setenv("DEVRADAR_AUTH_ENABLED", "false")
    monkeypatch.setenv("DEVRADAR_LOCAL_NO_LOGIN_ENABLED", "true")
    upgrade_database(fresh_postgresql_url)
    with TestClient(app) as client:
        first = client.get("/api/v1/auth/me")
        second = client.get("/api/v1/auth/me")
        assert first.status_code == second.status_code == 200
        assert first.json()["data"] == {"username": "local-operator", "role": "operator"}
        assert "set-cookie" not in first.headers
    with Session(_database_engine(fresh_postgresql_url)) as session:
        assert session.scalar(select(func.count()).select_from(User)) == 1
```

Thêm case mutation với Origin ngoài allow-list trả `403 csrf_origin_invalid`, và `POST /auth/logout` trong local mode trả `403 auth_disabled` thay vì dereference session rỗng.

- [ ] **Step 2: Chạy test và xác nhận RED**

Run: `.venv\Scripts\python -m pytest tests/integration/test_auth_api.py -q`

Expected: test local mode FAIL với `auth_disabled` từ `/auth/me`.

- [ ] **Step 3: Tạo singleton local operator idempotently**

```python
LOCAL_OPERATOR_USERNAME = "local-operator"
LOCAL_OPERATOR_PASSWORD_DISABLED = (
    "local-no-login-disabled$0000000000000000000000000000000000000000"
)


def get_or_create_local_operator(session: Session) -> User:
    user = session.scalar(select(User).where(User.username == LOCAL_OPERATOR_USERNAME))
    if user is None:
        now = datetime.now(UTC)
        user = User(
            username=LOCAL_OPERATOR_USERNAME,
            password_hash=LOCAL_OPERATOR_PASSWORD_DISABLED,
            role=AuthRole.OPERATOR.value,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        session.add(user)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            user = session.scalar(select(User).where(User.username == LOCAL_OPERATOR_USERNAME))
            if user is None:
                raise
    if not user.is_active or user.role != AuthRole.OPERATOR.value:
        raise LocalOperatorUnavailable("local_operator_invalid")
    return user
```

- [ ] **Step 4: Cho dependencies trả local `AuthContext` nhưng không tạo session**

```python
@dataclass(frozen=True, slots=True)
class AuthContext:
    user: User
    auth_session: AuthSession | None


def _local_context(session: Session) -> AuthContext:
    return AuthContext(user=get_or_create_local_operator(session), auth_session=None)


def require_authenticated_user(...):
    if auth_enabled():
        return _load_context(session, session_token)
    if local_no_login_enabled():
        return _local_context(session)
    raise ApiContractError(403, "auth_disabled", "Authentication is disabled for this deployment.")


def require_csrf(...):
    context = require_authenticated_user(request, session, session_token)
    if context.auth_session is None:
        _validate_origin(request)
    else:
        validate_csrf(request, context)
    return context
```

`require_owner_hash()` và `require_operator()` dùng cùng local context khi flag bật; auth-disabled không có flag vẫn giữ legacy owner/operator behavior hiện hành. `logout()` reject local context bằng stable `auth_disabled` trước khi chạm `revoked_at`.

- [ ] **Step 5: Chạy test integration và regression auth**

Run: `.venv\Scripts\python -m pytest tests/integration/test_auth_api.py tests/test_auth_service.py tests/test_security_config.py -q`

Expected: PASS; session auth, legacy local mode và explicit local no-login cùng giữ contract riêng.

- [ ] **Step 6: Commit identity boundary**

```powershell
git add src/devradar/auth/local_operator.py src/devradar/auth/dependencies.py src/devradar/api/auth.py tests/integration/test_auth_api.py
git commit -m "feat: resolve local operator without login"
```

### Task 3: Chứng minh Custom Sources owner scope trong local mode

**Files:**
- Modify: `tests/integration/test_custom_source_api.py`

- [ ] **Step 1: Viết test fail cho create/list/reuse owner không session**

```python
@pytest.mark.postgresql
def test_custom_sources_work_in_explicit_local_no_login_mode(
    fresh_postgresql_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEVRADAR_DATABASE_URL", fresh_postgresql_url)
    monkeypatch.setenv("DEVRADAR_DEPLOYMENT_CLASS", "LOCALHOST_SERVICE")
    monkeypatch.setenv("DEVRADAR_AUTH_ENABLED", "false")
    monkeypatch.setenv("DEVRADAR_LOCAL_NO_LOGIN_ENABLED", "true")
    monkeypatch.setenv("DEVRADAR_CUSTOM_SOURCES_LOCAL_ENABLED", "true")
    upgrade_database(fresh_postgresql_url)
    with TestClient(app) as client:
        created = client.post("/api/v1/custom-sources", json=_payload())
        listed = client.get("/api/v1/custom-sources")
        assert created.status_code == 201
        assert listed.status_code == 200
        assert listed.json()["data"][0]["id"] == created.json()["data"]["id"]
```

Thêm request có `Origin: https://attacker.test` và xác nhận mutation trả `403 csrf_origin_invalid`.

- [ ] **Step 2: Chạy test và xác nhận RED rồi GREEN bằng Task 2**

Run: `.venv\Scripts\python -m pytest tests/integration/test_custom_source_api.py -q`

Expected trước Task 2: FAIL `auth_disabled`; sau Task 2: PASS, không cần sửa API custom source.

- [ ] **Step 3: Commit regression test**

```powershell
git add tests/integration/test_custom_source_api.py
git commit -m "test: cover local no-login custom sources"
```

### Task 4: Đồng bộ Compose/web mode và docs contract

**Files:**
- Modify: `.env.example`
- Modify: `.env.production.example`
- Modify: `compose.yaml`
- Modify: `web/src/lib/deployment-mode.ts`
- Modify: `web/src/components/app-shell.tsx`
- Modify: `web/src/components/auth-controls.tsx`
- Modify: `web/src/app/login/page.tsx`
- Modify: `web/tests/routes.test.mjs`
- Modify: `docs/API.md`
- Modify: `docs/OPERATIONS.md`
- Modify: `README.md`

- [ ] **Step 1: Viết static web test fail cho explicit server flag**

```javascript
test("local no-login hides auth controls and redirects login server-side", async () => {
  const mode = await source("src/lib/deployment-mode.ts");
  const shell = await source("src/components/app-shell.tsx");
  const login = await source("src/app/login/page.tsx");
  assert.match(mode, /DEVRADAR_LOCAL_NO_LOGIN_ENABLED/);
  assert.match(shell, /localNoLoginEnabled/);
  assert.match(login, /redirect\("\/"\)/);
});
```

- [ ] **Step 2: Chạy test và xác nhận RED**

Run: `npm test --prefix web`

Expected: FAIL vì `deployment-mode.ts` chưa tồn tại.

- [ ] **Step 3: Thêm server-only environment helper và web behavior**

```typescript
export function localNoLoginEnabled(): boolean {
  return process.env.DEVRADAR_LOCAL_NO_LOGIN_ENABLED?.trim().toLowerCase() === "true";
}
```

`AppShell` truyền `localNoLoginEnabled` vào `AuthControls`; component trả `null` trong mode này. `LoginPage` là async Server Component và gọi `redirect("/")` khi flag bật. Compose truyền cùng flag vào `api`, `crawler` và `web`; committed examples đặt `DEVRADAR_LOCAL_NO_LOGIN_ENABLED=false`.

- [ ] **Step 4: Chạy web test/type/build và Python config test**

Run: `npm run check --prefix web`

Run: `.venv\Scripts\python -m pytest tests/test_security_config.py tests/test_production_deployment_contract.py tests/test_web_deployment_contract.py -q`

Expected: tất cả PASS.

- [ ] **Step 5: Cập nhật docs với local-only boundary và commit**

```powershell
git add .env.example .env.production.example compose.yaml web/src/lib/deployment-mode.ts web/src/components/app-shell.tsx web/src/components/auth-controls.tsx web/src/app/login/page.tsx web/tests/routes.test.mjs docs/API.md docs/OPERATIONS.md README.md
git commit -m "feat: expose local no-login mode to web"
```
