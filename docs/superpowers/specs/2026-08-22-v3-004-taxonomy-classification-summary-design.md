# V3-004 Taxonomy, classification và bounded summary — Design Spec

**Ngày:** 2026-08-22  
**Trạng thái:** Đã được user duyệt; triển khai tự động theo task board  
**Phase:** V3 — AI extraction, taxonomy và semantic search

## Mục tiêu

Mở rộng boundary intelligence sau V3-003 để DevRadar có:

- taxonomy versioned cho category của Skill và requirement type;
- role/job classification deterministic có evidence và trạng thái review rõ ràng;
- bounded summary được dựng từ claim/evidence đã kiểm chứng;
- contract typed để provider tương lai có thể trả candidate, nhưng chưa gọi DeepSeek production;
- fail-closed khi role mơ hồ, skill chưa map, evidence không tồn tại hoặc summary vượt giới hạn.

## Quyết định đã khóa

- Dùng chung alias map và `extract_skill_expectations()` hiện có; không tạo alias map thứ hai.
- Taxonomy version là `job-taxonomy-v1`; đổi alias/category phải bump version và không âm thầm sửa lịch sử.
- Skill unknown được giữ nguyên evidence với category `other`, nhưng outcome là `needs_review`, không tự coi là canonical mapping.
- Role classification chỉ nhận các role family có marker trong title/description; tie hoặc không có marker là `needs_review`, không đoán role.
- `levels` vẫn lấy từ deterministic canonical Job field; classification không override levels.
- Summary là output deterministic bounded; mỗi claim phải có evidence span xuất hiện trong canonical input. Không nhận salary, benefit, requirement hoặc skill chỉ xuất hiện trong text summary mà không có evidence.
- Không thêm endpoint, bảng persistence, SDK, model call, pgvector, queue hoặc dependency phase sau trong V3-004.

## Phạm vi và non-goal

### Trong phạm vi

- typed taxonomy/category/role/evidence models;
- deterministic skill categorization và requirement type preservation;
- deterministic role classification với confidence bounded và ambiguity handling;
- bounded summary builder và candidate validator;
- unit tests cho alias, unknown/ambiguous role, evidence, length, newline, prompt-injection-like text và unsupported claim;
- docs/evidence/task board update.

### Ngoài phạm vi

- production DeepSeek adapter hoặc gửi JD/CV thật tới external provider;
- lưu classification/summary vào PostgreSQL hoặc backfill 78 jobs;
- public REST endpoint hoặc UI;
- embeddings, pgvector, semantic search và trend API của V3-005;
- agent/planner/validator của V4.

## Contract

### Taxonomy

```text
taxonomyVersion = job-taxonomy-v1
skillCategory = language | framework | database | cloud | devops |
                messaging | testing | ai | tool | other
roleFamily = backend | frontend | mobile | data | devops | qa |
             security | product | design
requirementType = required | preferred | optional | mentioned
```

`TaxonomySkill` giữ `name`, `category`, `requirement_type`, `evidence`, `confidence` và version. Category map chỉ áp dụng cho canonical skill name; unknown không bị loại khỏi evidence nhưng tạo `needs_review`.

### Role classification

`RoleClassification` gồm role family, canonical levels, evidence claims, confidence, taxonomy/schema version. `ClassificationOutcome` trả `accepted`, `needs_review` hoặc `rejected` cùng safe `code/path/type` errors. Role evidence phải là substring của canonical title/description/level input.

### Bounded summary

`BoundedSummary` gồm `schema_version`, `text` tối đa 420 ký tự, tối đa 8 `SummaryEvidence` và taxonomy version. Builder chỉ dùng role/skill/level evidence đã accepted; summary không chứa raw JD, prompt hoặc rejected provider value.

Candidate validator kiểm tra strict object shape, text length/control characters, evidence presence trong source và exact deterministic rendering từ role/skill evidence. Unsupported prose/evidence hoặc extra field trả `rejected`.

## Luồng

```text
Job canonical fields
       |
       +--> existing skill extraction --> taxonomy category map
       |                                  |
       |                                  +--> unknown => needs_review
       |
       +--> role marker scoring ----------+--> unique winner => accepted
       |                                  +--> tie/no marker => needs_review
       |
       +--> bounded summary builder <----- accepted evidence only
                                          |
                                          +--> evidence/limits validate
```

Không có classification accepted thì summary giữ `needs_review`; ingestion và canonical Job vẫn thành công độc lập.

## Testing contract

- known aliases map category và giữ evidence/requirement type;
- unknown skill không bị đổi tên hoặc auto-accepted;
- role marker trong title thắng marker yếu trong description; tie/no marker cần review;
- levels không bị classification thay đổi;
- evidence thiếu, evidence ngoài source, newline/control char, extra field và summary >420 ký tự bị reject;
- prompt-injection-like source text chỉ được xem là data, không tạo tool/action hoặc claim mới;
- deterministic summary chỉ sinh claim có evidence, bounded tối đa 8 evidence;
- provider candidate validator không chấp nhận skill/role/benefit/salary không có evidence.

## Definition of Done mapping

- taxonomy/classification/summary typed contract và version tồn tại;
- unit test đỏ-xanh cho success, ambiguity, unknown, malformed và unsupported claim;
- không có production provider/API/persistence/dependency mới;
- AI/domain/operations/evidence cập nhật cùng thuật ngữ;
- V3 vẫn `in_progress`, V3-005/V3-006 chưa được đóng.
