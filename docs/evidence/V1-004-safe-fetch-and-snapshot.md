# V1-004 — Safe fetch và raw snapshot persistence

**Ngày kiểm tra:** 2026-08-21

**Kết quả:** `pass`

**Scope:** HTTPS fetch cho source HTTP đã approved và persistence một `FetchResult` thành `RawJobSnapshot` trong transaction do caller sở hữu. Không gồm concrete source adapter, browser path MoMo, workflow retry, Job upsert hoặc domain API.

## 1. Fetch boundary

[Safe HTTP implementation](../../src/devradar/ingestion/safe_http.py) dùng Python standard library, không thêm dependency:

- chỉ nhận HTTPS host/path trong `FetchPolicy`; reject user-info, custom port, fragment, control/whitespace và path ngoài prefix;
- resolve toàn bộ IPv4/IPv6, reject cả answer set nếu rỗng, invalid hoặc có bất kỳ address không `is_global`;
- connect trực tiếp tới numeric IP đã kiểm tra, trong khi TLS SNI/certificate validation vẫn dùng approved hostname;
- tự xử lý redirect để revalidate URL và DNS/IP ở từng hop;
- concurrency 1 và throttle theo source; socket timeout, redirect count, response byte, content type và content encoding đều bounded;
- chỉ yêu cầu `Accept-Encoding: identity`; đọc tối đa `max_response_bytes + 1` để phát hiện body vượt limit;
- lỗi trả stable code, retryability, bounded HTTP status/`Retry-After` và safe summary không chứa URL/query/socket detail.

Runtime behavior dựa trên tài liệu Python 3.13 cho [numeric IPv4/IPv6 socket address và `getaddrinfo`](https://docs.python.org/3.13/library/socket.html#socket.getaddrinfo), [TLS `SSLContext.wrap_socket`](https://docs.python.org/3.13/library/ssl.html#ssl.SSLContext.wrap_socket), [`HTTPResponse`](https://docs.python.org/3.13/library/http.client.html#http.client.HTTPResponse) và [`ipaddress.is_global`](https://docs.python.org/3.13/library/ipaddress.html#ipaddress.IPv4Address.is_global).

## 2. Snapshot boundary

[Snapshot persistence](../../src/devradar/ingestion/snapshot_persistence.py):

- chỉ nhận config `approved` và `CrawlRun` đã persist;
- đối chiếu persisted `Source`, allowed host và `CrawlRun.config_version` với active registry config;
- revalidate final URL, URL/external ID/content-type length và byte limit;
- strict-decode charset đã khai báo, default UTF-8; reject unknown codec, invalid byte sequence và null character;
- giữ run/source/URL/external ID/fetch time/status/content type/raw hash/raw text, với `parse_status=pending`;
- chỉ `session.flush()`, không commit; caller quyết định atomic commit/rollback cho cả ingestion item/run.

## 3. Security negative evidence

Unit tests dùng injected resolver/transport/time, không gọi network. Các case pass gồm:

- loopback, metadata link-local, IPv6 loopback và mixed public/private DNS bị chặn trước transport;
- redirect thoát allow-list và vượt redirect limit bị chặn;
- path ngoài prefix bị chặn trước DNS;
- unsupported content type/encoding, invalid/oversized `Content-Length` và streamed body overflow bị chặn;
- 429/5xx/4xx, timeout, throttle và safe error semantics;
- source registry/config version mismatch, candidate source và invalid UTF-8 không tạo snapshot mới.

`8.8.8.8` trong unit test chỉ là giá trị address đi qua fake transport; test không mở outbound socket.

## 4. PostgreSQL và transaction evidence

Integration test chạy migration trên PostgreSQL 18.6 database mới, seed exact NAVER approved `Source` + `CrawlRun`, persist một JSON result và kiểm tra đầy đủ provenance/hash/raw content/`pending`.

Trước caller commit, session PostgreSQL thứ hai thấy `0` snapshot; sau commit thấy `1`. Điều này chứng minh helper không commit ngoài transaction của caller. Candidate/config mismatch và invalid encoding được chạy trên cùng database thật, count vẫn giữ `1`.

## 5. Bounded live smoke

Một GET duy nhất qua implementation tới NAVER Vietnam public Greenhouse endpoint đã approved; không gọi application endpoint và không dùng GeoComply/Lever hoặc MoMo API nền:

| Thuộc tính | Giá trị |
|---|---:|
| HTTP status | `200` |
| Content type | `application/json` |
| Response bytes | `8,809` |
| SHA-256 | `ccd1209fbb1569e03aec117d3c8de33b35d7fb3d412a04bc0e56bebb0a3e465e` |
| `meta.total` / jobs count | `14 / 14` |

Số lượng và hash là observation tại thời điểm smoke, không phải production baseline hoặc license tái xuất bản nội dung.

## 6. Verification

| Gate | Kết quả |
|---|---|
| Safe HTTP narrow tests | `17 passed` |
| PostgreSQL snapshot integration | `1 passed` |
| Full suite với PostgreSQL opt-in | `55 passed`, không warning |
| Ruff check/format | Pass |
| mypy strict | Pass, 25 source/test files |
| `pip check` / Alembic drift | Pass / no drift |

## 7. Boundary còn mở

- Fetcher chỉ phục vụ HTTP adapters; MoMo browser security boundary thuộc `V1-008` và không được nới policy này.
- V1 chưa tự retry; error metadata dành cho caller và V2 retry workflow sau này.
- Concrete parsing/list completeness thuộc `V1-006`–`V1-008`.
- Idempotent Job upsert và rollback toàn item/run thuộc `V1-009`.
- Production deployment vẫn cần egress filtering như defense in depth; V1 pinned connection loại DNS resolve lần hai trong application path nhưng không thay network policy.
