# V5-004 Task 1 — JobMatch scoring evaluation

## Kết quả

Task 1 khóa evaluation contract synthetic và chọn `job-match-scoring-v2`. Scoring là ranking heuristic có version, không phải xác suất được tuyển dụng và không dùng để tự động quyết định tuyển dụng. V2 invalidates row cũ sau khi requirement weights được sửa; profile embedding input dùng `resume-match-embedding-input-v2` sau khi canonical field order được sửa.

| Thuộc tính | Giá trị |
|---|---|
| Dataset | `tests/fixtures/matching/job_match_eval_v1.json` |
| Evaluation version | `job-match-eval-v1` |
| Schema version | `job-match-eval-schema-v1` |
| SHA-256 | `31eff10b18c9883e7041cba56173ddec57ac8f3ee74e3c866765b30c0d1783e2` |
| Provenance | `project-authored-synthetic-no-third-party-content` |
| Split | 4 development + 8 held-out |
| Candidate groups | 12, tối thiểu 3 candidate mỗi case |

Fixture bao phủ bilingual, deterministic tie, missing skill/extraction/location/experience/role, overqualified, semantic conflict và sparse evidence. Không có CV/JD thật, nội dung bên thứ ba, URL, PII hoặc secret.

## Contract đã chọn

| Component | Weight |
|---|---:|
| skill | 0.40 |
| semantic | 0.25 |
| experience | 0.15 |
| location | 0.10 |
| role | 0.10 |

Component vắng mặt đóng góp `0`; hệ thống không renormalize phần weight còn lại. `evidenceCoverage` cho biết tổng weight có bằng chứng. Điểm và coverage được làm tròn half-up tới bốn chữ số; thứ tự hòa điểm là `score desc, candidate id asc`. Skill evidence phải được sort, deduplicate và disjoint giữa `matchedSkills`/`missingSkills`.

`role` được dùng thay cho `level` vì `ResumeProfile` hiện có role evidence nhưng chưa có level/preference đáng tin cậy. Khi profile contract có level preference rõ ràng, đó sẽ là scoring version mới cùng evaluation mới.

## Development comparison

| Weights | Top-1 | MRR | NDCG@5 |
|---|---:|---:|---:|
| skill-heavy (`0.50/0.20/0.15/0.05/0.10`) | 0.7500 | 0.8750 | 0.9275 |
| semantic-heavy (`0.30/0.40/0.15/0.05/0.10`) | 0.7500 | 0.8750 | 0.9275 |
| recommended (`0.40/0.25/0.15/0.10/0.10`) | 1.0000 | 1.0000 | 1.0000 |

Balanced weights thắng cả hai alternative trên development theo MRR và NDCG@5, đồng thời xử lý tốt các case xung đột skill/semantic và evidence role/location.

## Held-out release gate

| Metric | Gate | Kết quả |
|---|---:|---:|
| Top-1 accuracy | >= 0.8750 | 1.0000 |
| MRR | >= 0.9000 | 1.0000 |
| NDCG@5 | >= 0.9000 | 1.0000 |
| Score range rate | 1.0000 | 1.0000 |
| Monotonicity rate | 1.0000 | 1.0000 |
| Stable tie rate | 1.0000 | 1.0000 |
| Missing behavior rate | 1.0000 | 1.0000 |
| Evidence closure rate | 1.0000 | 1.0000 |
| Unsupported claim rate | 0.0000 | 0.0000 |

## Verification

```text
pytest tests/test_job_match_evaluation.py -q   5 passed
ruff check scoring/evaluation/test files       All checks passed
ruff format --check scoring/evaluation/tests   clean
mypy scoring/evaluation/test files             no issues
```

CLI evaluation chạy với `PYTHONPATH=src` và chỉ xuất version, dataset hash, weights và metrics; không xuất candidate text, CV/JD, vector hoặc owner identity. Default evaluation không chạm network, PostgreSQL hay external LLM.
