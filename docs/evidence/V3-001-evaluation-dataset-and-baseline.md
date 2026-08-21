# V3-001 — Labeled evaluation dataset và deterministic baseline

## Kết quả

V3 có dataset extraction đầu tiên được khóa bằng version/schema/hash trước khi chọn LLM provider:

- dataset: `job-extraction-eval-v1`;
- schema: `job-extraction-eval-schema-v1`;
- file: `tests/fixtures/ai/job_extraction_eval_v1.json`;
- SHA-256: `664758cac3e263f28e4afad77c209f77301b9e45ef3ffd1100359bb325578512`;
- provenance: 100% project-authored synthetic, không copy JD thật, secret, PII hoặc third-party content;
- split: 4 development + 8 held-out; release comparison chỉ dùng held-out.

Không thêm ADR vì đây là evaluation contract versioned có thể tiến hóa bằng dataset/schema version mới, không phải dependency hoặc kiến trúc khó đảo ngược. Provider, prompt, pgvector và production taxonomy vẫn chưa được chọn.

## Coverage

Held-out có đủ `vi`, `en`, `mixed` và các nhóm bắt buộc:

- required/optional skill và alias normalization;
- multi/ambiguous level cùng experience mơ hồ;
- salary/location edge và field vắng mặt;
- short/malformed/noisy description;
- negation;
- prompt-injection-like text và unsupported claim.

Mỗi skill label có exact evidence span trong title/description. Loader fail closed với extra field, sai enum/version, duplicate case/label hoặc evidence không tồn tại.

## Baseline held-out

`deterministic-keyword-v1` dùng normalizer V1 hiện có và keyword/requirement marker nhỏ, không gọi network/model:

| Metric | Baseline |
|---|---:|
| Cases | 8 |
| Skill precision | 0.9545 |
| Skill recall | 0.9545 |
| Skill F1, gồm requirement type | 0.9545 |
| Unsupported skill rate | 0.0455 |
| Level exact accuracy | 1.0000 |
| Experience exact accuracy | 0.8750 |
| Salary exact accuracy | 1.0000 |
| Location exact accuracy | 1.0000 |
| Deterministic complete rate | 0.6250 |

Hai gap làm baseline không perfect là optional `Azure` ngoài lexicon và câu prompt injection nhắc `Kubernetes` nhưng không phải requirement. Case experience mơ hồ cũng chứng minh parser số đơn giản cần giữ `null/review` thay vì tự suy đoán range.

## Target release cho V3 extraction

Target dưới đây được đặt từ baseline, áp dụng cho cùng held-out version trước khi AI output ảnh hưởng canonical data:

| Metric | Gate |
|---|---:|
| Skill F1, gồm requirement type | `>= 0.9700` |
| Unsupported skill/hallucination rate | `0.0000` |
| Level exact accuracy | `>= 1.0000` |
| Experience exact accuracy | `>= 0.8750` |
| Salary exact accuracy | `>= 1.0000` |
| Location exact accuracy | `>= 1.0000` |
| Complete accepted result | `>= 0.8750` |
| Accepted schema/evidence validation | `1.0000` hard gate |

Target latency/token/cost chỉ được đặt ở `V3-002` sau provider spike có measured baseline. Role taxonomy và summary correctness được khóa ở `V3-004`; V3-001 không giả lập metric cho contract chưa tồn tại. Development split được phép dùng khi chỉnh parser/prompt, held-out không được dùng làm few-shot example hoặc tuning input.

## Verification

```text
python -m pytest tests/test_ai_evaluation.py    3 passed
python -m pytest                               126 passed
python -m ruff check .                         All checks passed
python -m ruff format --check .                110 files already formatted
python -m mypy                                 no issues in 58 source files
python -m pip check                            No broken requirements found
Markdown local-link check                      48 files pass
```

Regression test khóa version, split/risk coverage, synthetic/no-URL/no-email boundary, missing evidence, duplicate identity và exact aggregate baseline. Default evaluation không chạm PostgreSQL, source hoặc LLM.
