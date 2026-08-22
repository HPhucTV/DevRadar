# V3-006 Evaluation, scale và closeout — Design Spec

**Ngày:** 2026-08-22  
**Trạng thái:** Được user ủy quyền triển khai tự động  
**Phase:** V3 — AI extraction, taxonomy và semantic search

## Mục tiêu

V3-006 tạo release-quality semantic evaluation/cost/latency artifact, refresh inventory từ đúng ba source approved và audit toàn bộ V3 exit criteria. Task chỉ đóng Phase V3 khi inventory có tối thiểu 500 canonical Job từ complete reproducible runs; synthetic fixture, partial smoke và waiver không owner/review date không được thay thế gate này.

## Các hướng đã cân nhắc

### 1. Hạ count gate hoặc tự cấp waiver

Rejected. Không có owner/review date và điều này làm claim analytics scale vượt evidence.

### 2. Thêm source/crawl URL mới để đạt 500

Rejected trong V3-006. Source mới cần policy/robots/terms/technical approval cùng adapter task riêng; arbitrary URL bị contract cấm.

### 3. Hoàn tất measurable gates, refresh allow-list rồi block honestly nếu còn thiếu

Accepted. Đây là slice nhỏ nhất tạo evidence thật mà không đổi source/privacy/domain contract.

## Semantic evaluation contract

Tạo dataset `semantic-retrieval-eval-v1` project-authored synthetic, không chứa JD thật, URL, PII hoặc secret. Dataset có development và held-out split, nội dung Việt/Anh/mixed, documents có unique ID/role label và queries trỏ exact relevant document IDs. Validation fail closed với duplicate identity, split rỗng, unknown relevant document, repeated query hoặc provenance/version sai.

Model-choice spike cũ không được tính là release held-out. Fixture mới được khóa/hash trước lần live run đầu; sau khi chạy không sửa query/label để làm metric đẹp. Nếu metric fail, model giữ trạng thái chưa đạt hoặc dataset version mới phải giải thích thay đổi và không gọi lại bản cũ là held-out.

Evaluator dùng cosine trên vector đã validate, deterministic ranking theo score giảm dần rồi document ID. Report gồm:

- case count và language coverage;
- top-1 accuracy;
- MRR;
- Recall@5;
- cross-language top-1;
- embedding latency p50/p95 cho passage/query;
- dimension/finite/model/input identity;
- local monetary cost luôn `USD 0`, cùng model/image/cache footprint đo từ artifact thực.

Release target được đặt trước live run: held-out top-1 `>=0.90`, MRR `>=0.95`, Recall@5 `=1.0`, cross-language top-1 `>=0.85`, dimension 384 và mọi vector finite. Không đặt latency SLO giả; V3-006 ghi baseline p50/p95 và chỉ tối ưu khi phép đo chứng minh cần.

## Implementation boundary

`intelligence.semantic_evaluation` sở hữu typed dataset, deterministic evaluator, percentile calculation và một fixed-model CLI/module runner. Runner nhận path dataset local để evaluation reproducible nhưng không nhận provider/model/URL tùy ý. Nó dùng `LocalEmbeddingModel` hiện hành và chỉ in aggregate JSON, không in document/query text hoặc vector.

Default tests không tải model/network. Unit tests inject fake vector callable để chứng minh ranking, tie-break, metric và malformed dataset behavior. Một opt-in live command chạy fixed model local sau artifact download.

Không persist evaluation row hoặc thêm bảng/service/SDK. Evidence Markdown là release artifact phù hợp scope portfolio hiện tại.

## Inventory, extraction và scale flow

1. Snapshot live baseline: Job count theo source, latest complete run, embedding/extraction coverage.
2. Chạy full on-demand crawl lần lượt đúng `naver-vietnam-greenhouse`, `vng-careers`, `momo-careers`; không `--max-items`.
3. Chỉ count inventory sau run `succeeded + coverage=complete`; failed/partial/anomaly không tạo completeness hoặc removal signal.
4. Backfill current Job embeddings bằng batch bounded; measure selected/created/cache hit/stale, passage latency p50/p95 và local footprint.
5. Extraction coverage được audit. Không gửi source JD thật tới DeepSeek vì source approval/privacy boundary chưa cho phép; deterministic extraction có thể chạy local nếu application đã có bounded operator path, còn thiếu path không được giải quyết bằng production provider adapter ngoài scope.
6. Chạy keyword/semantic/skill-trend API smoke và PostgreSQL exact-query timing trên current compatible vectors.

Nếu complete inventory sau refresh vẫn `<500`, V3-006 được ghi `Blocked` với observed count, gap và điều kiện mở khóa: approved source inventory tăng tự nhiên tới gate hoặc source approval + adapter task riêng bổ sung nguồn hợp lệ. Board dùng `Blocked`; roadmap/phase giữ `v3 in_progress`; không push và không mở V4.

## Failure và privacy

- Source fail/partial: ghi safe run ID/status/count, không retry vô hạn và không tăng removal/count evidence.
- Model missing/corrupt: semantic evaluation fail closed; ingestion/full crawl vẫn độc lập.
- Evaluator malformed vector: reject aggregate run, không serialize vector.
- Query/document text không vào log/report; chỉ ID/version/metric bounded.
- DeepSeek credential không được đọc/in/commit; live source JD không gửi external model.
- Dataset/model artifact/cache nằm trong ignored path hoặc tracked synthetic fixture tương ứng; model binary không vào Git.

## Definition of Done

- semantic dataset/schema/hash và pre-run targets được commit;
- deterministic evaluator tests có RED→GREEN evidence và live fixed-model run tạo aggregate report;
- three-source full refresh outcomes và canonical count có evidence;
- current embedding backfill/search latency/footprint/cost được đo;
- extraction/generation failure independence và all V3 exit criteria được audit;
- full PostgreSQL/static/migration/Compose/Markdown/security gates pass;
- nếu `>=500` và mọi gate đạt: V3 complete, V4 Ready và push; nếu không: V3-006 Blocked, không push.

## Tự kiểm tra spec

Spec không có placeholder, không thay đổi ADR/source/API contract, không dùng waiver vô chủ và không trộn semantic synthetic quality với real-inventory scale evidence. Mọi outcome có nhánh pass/block rõ ràng.
