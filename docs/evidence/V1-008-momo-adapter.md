# V1-008 — MoMo Careers adapter

**Ngày kiểm tra:** 2026-08-21

**Kết quả:** `pass`

**Scope:** browser-assisted discovery cho approved source `momo-careers`, exact public load-more flow, complete listing identity, safe detail fetch/parser và browser trust-boundary controls. Không gồm Job upsert, run persistence/counters, scheduler, containerized browser crawler hoặc public API.

## 1. Dependency decision

Bounded source spike đã chứng minh HTTP SSR chỉ chứa batch đầu, trong khi approval cấm replay frontend API trực tiếp. Stdlib/HTTP adapter hiện có không thể thực hiện public `Xem thêm`; Playwright là dependency nhỏ nhất đáp ứng current source contract. Runtime pin `playwright==1.62.0`; lockfile sinh bằng `pip-tools==7.6.1`, clean hash-locked install pass và local browser list xác nhận Chromium/headless-shell build `1234` khớp package.

Implementation dùng documented Playwright patterns:

- fresh non-persistent `browser.new_context()` và explicit close: [Browser/BrowserContext API](https://playwright.dev/python/docs/api/class-browser#browser-new-context);
- context routing áp dụng cả popup và chặn mọi request ngoài allow-list: [network routing](https://playwright.dev/python/docs/network#handle-requests);
- `service_workers="block"` để route không bị service worker bypass: [missing network events](https://playwright.dev/python/docs/network#missing-network-events-and-service-workers);
- WebSocket route được đăng ký trước page và đóng policy violation: [BrowserContext WebSocket routing](https://playwright.dev/python/docs/api/class-browsercontext#browser-context-route-web-socket), [WebSocketRoute close](https://playwright.dev/python/docs/api/class-websocketroute#web-socket-route-close).

`page.wait_for_timeout` chỉ dùng cho source throttle 5 giây, không dùng để xác nhận UI ready; response event và DOM attachment mới là completion signal.

## 2. Browser trust boundary

[Adapter implementation](../../src/devradar/ingestion/adapters/momo.py) khóa:

- source/config phải là exact approved `momo-careers`, fixed group `DGM.0001` / `Trung tâm Công nghệ Thông tin`;
- trước launch, cả `momo.careers` và `aws.momo.vn` phải resolve, và bất kỳ private/reserved address nào làm run fail closed;
- chỉ `GET /jobs-opening?groups=DGM.0001`, same-origin `/_next/static/` và exact UI-generated load-more path/query được route tiếp;
- không modify/reconstruct header, không gọi `APIRequestContext`, không nhận URL/filter từ user/model;
- fresh context có `accept_downloads=False`, `service_workers="block"`, cleared permissions và không persistent profile;
- popup/download/WebSocket bị đóng/cancel và làm run policy-failed; analytics, media host, detail prefetch, custom port, private IP, POST, extra query/control đều default deny;
- 401/403/429, challenge marker, timeout, response type/size violation và browser crash trả safe bounded error.

Browser DNS validation ở application layer vẫn có TOCTOU vì Chromium tự resolve khi connect. Network/container egress policy là lớp bắt buộc trước production-like run; `V1-012` phải cài browser/system dependencies, sandbox/least-privilege profile, resource budget và egress control. Local live evidence không phải Docker readiness.

## 3. Completeness và identity

Batch đầu parse từ one complete SSR `__NEXT_DATA__`. Mỗi click chờ exact response do UI tạo với approved group/sort, batch size `12` và cumulative `lastIdx`; adapter đọc envelope `Result/Error/Data` nhưng không replay request.

Run chỉ trả listing khi:

- group ID/name, filter/query, `TotalItems` và `PageCount` giữ nguyên;
- mỗi observed batch có 1–12 items, `LastIndex` và DOM count tăng đúng cumulative count;
- mỗi `jobId` là positive integer/digit string và unique; `subdirectory` là bounded lowercase ASCII slug kết thúc bằng exact `-{jobId}`;
- union response identities khớp final DOM identities, count đúng `TotalItems`, số observed pages đúng `PageCount` và button biến mất;
- failed attempt xóa complete-discovery cache cũ, nên stale listing không thể fetch detail.

Source field `Count=12` biểu diễn requested page size, kể cả final response chỉ có một `Item`; implementation không diễn giải `Count` thành returned-item count. Slug change giữ cùng external identity nhưng cập nhật canonical URL observation; slug/ID mismatch và duplicate ID fail closed.

## 4. Deterministic detail parsing

Detail chỉ GET qua `SafeHttpFetcher` cho exact listing sau complete discovery. Parser:

- đối chiếu source key, `/jobs/[detail]`, snapshot `jobId`, detail slug/URL và approved division group;
- chỉ giữ title, location, job code/type và division provenance;
- ghép distinct `jobDesc/jobResp/jobRequire`, strip `script/style/template/noscript` và normalize plaintext;
- redact email/Vietnam phone khỏi canonical description, thêm warning `contact_data_redacted`;
- bỏ `original`, `relatedJobs`, application flags, candidate motivation/form data và không suy diễn salary/posted date/level/experience.

Contact-redaction helper được dùng chung với VNG adapter; VNG regression suite vẫn pass.

## 5. Fixture và negative evidence

[Fixture set](../../tests/fixtures/momo) gồm SSR list/master/filter, final load-more envelope với `Count=12` nhưng một item, happy/missing-optional detail, unsafe markup, contact/application data.

16 MoMo tests pass, bao phủ:

- SSR + UI batch completeness, exact detail fetch và stale-listing protection;
- optional field, string/integer ID, slug mismatch/change, duplicate, page/count/DOM/control conflict;
- early control loss/timeout/challenge propagation và failed-run cache invalidation;
- default-deny host/path/query/method, private DNS, popup, download và WebSocket;
- 401/403/429, candidate/wrong config, malformed JSON và safe parse failure.

Default test dùng injected browser capture/response, không launch browser và không chạm network.

## 6. Full on-demand local evidence

Sau fixture/browser-policy/incomplete-run gates, một final on-demand adapter run dùng public filtered UI tới complete state, rồi fetch/parse đúng một discovered detail:

| Observation | Giá trị |
|---|---:|
| Approved filter | `DGM.0001` — `Trung tâm Công nghệ Thông tin` |
| Total unique jobs | `37` |
| Observed pages | `4` |
| Batch coverage | `12 + 12 + 12 + 1` |
| First external ID | `17404` |
| Detail parse result | `ParsedJob` |

Run dùng one browser page, concurrency 1, 5-second action interval, public button và UI-generated responses. Không gọi application endpoint, không replay API, không log raw JD/token và không persist dữ liệu. Count là observation ngày kiểm tra, không phải production baseline hoặc license tái xuất bản.

## 7. Verification

| Gate | Kết quả |
|---|---|
| MoMo fixture/security tests | `16 passed` |
| Full suite với PostgreSQL opt-in | `97 passed`, không warning |
| Ruff check/format | Pass, `66` files |
| mypy strict | Pass, `33` source/test files |
| `pip check` / Alembic drift | Pass / no drift (integration gate) |
| Clean hash-locked install | Pass |
| Chromium version match | Playwright `1.62.0`, browser build `1234` |
| Existing non-root API image rebuild | Pass; Playwright package installed, browser executable intentionally not claimed |
| Teardown | Database/network removed; named volume preserved; ports `8000/55432` không listen |

## 8. Boundary còn mở

- Raw snapshot → normalized Job transaction, source-scoped dedup và idempotent replay thuộc `V1-009`.
- Current API Docker image chưa cài Chromium/system dependencies. Playwright docs yêu cầu browser + system dependencies và khuyến nghị non-root/seccomp cho crawling: [official Docker guidance](https://playwright.dev/python/docs/docker). Container browser/sandbox/egress verification thuộc `V1-012`.
- Approval chỉ cho local non-commercial/on-demand V1; schedule, public full-JD exposure, commercial reuse, external LLM và AI training chưa được duyệt.
