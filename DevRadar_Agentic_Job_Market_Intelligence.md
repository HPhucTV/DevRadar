# DevRadar — Agentic Job Market Intelligence Platform

## 1. Tổng quan ý tưởng

**DevRadar** là một nền tảng thu thập, phân tích và theo dõi thị trường tuyển dụng IT bằng cách kết hợp:

- Web scraping / crawling
- Automation / scheduling
- Backend API
- Database
- AI / LLM
- Agentic AI
- Embedding / semantic search
- Dashboard
- Monitoring
- Docker / CI/CD

Mục tiêu của project là xây dựng một hệ thống có khả năng:

1. Định kỳ thu thập dữ liệu tuyển dụng từ nhiều nguồn công khai.
2. Chuẩn hóa và lưu trữ dữ liệu job.
3. Phát hiện job mới, job thay đổi, job bị xóa.
4. Dùng AI để trích xuất thông tin có cấu trúc từ Job Description.
5. Phân tích xu hướng kỹ năng trên thị trường.
6. So khớp CV với job.
7. Dùng Agentic AI để điều phối pipeline, validate dữ liệu, retry khi lỗi và tạo insight.
8. Hiển thị kết quả trên dashboard.
9. Gửi cảnh báo khi xuất hiện job phù hợp.

Đây không chỉ là một project "crawler + GPT", mà là một hệ thống data intelligence có nhiều thành phần gần với một sản phẩm thực tế.

---

# 2. Bài toán project giải quyết

Sinh viên hoặc developer khi tìm việc thường gặp các vấn đề:

- Phải kiểm tra nhiều website tuyển dụng.
- Job bị trùng giữa nhiều nguồn.
- Khó theo dõi job mới.
- Khó biết công nghệ nào đang được tuyển nhiều.
- Khó đánh giá CV của mình phù hợp với job nào.
- Không biết mình đang thiếu kỹ năng gì.
- Không có dữ liệu lịch sử để phân tích xu hướng tuyển dụng.

DevRadar giải quyết các vấn đề trên bằng cách tự động hóa toàn bộ quá trình:

```text
Public Job Sources
        ↓
Scheduled Crawling
        ↓
Data Normalization
        ↓
Deduplication
        ↓
AI Extraction
        ↓
Validation
        ↓
Database
        ↓
Analysis / Matching
        ↓
Dashboard / Notification
```

---

# 3. Đối tượng sử dụng

## 3.1. Sinh viên IT

Có thể sử dụng DevRadar để:

- tìm internship,
- tìm fresher / junior job,
- biết skill nào đang được yêu cầu nhiều,
- so sánh CV với thị trường,
- biết skill nào cần học thêm.

## 3.2. Developer

Có thể sử dụng để:

- theo dõi job mới,
- theo dõi mức độ phổ biến của công nghệ,
- xem thị trường backend/frontend/data/AI,
- phân tích JD.

## 3.3. Recruiter hoặc HR

Trong tương lai có thể dùng để:

- theo dõi nhu cầu kỹ năng trên thị trường,
- benchmark tech stack,
- theo dõi xu hướng tuyển dụng.

---

# 4. Use Case chính

## UC1 — Crawl job định kỳ

Hệ thống định kỳ truy cập các nguồn tuyển dụng công khai và thu thập:

- Job title
- Company
- Location
- Job description
- Salary
- Level
- Experience
- Skills
- Posted date
- Job URL
- Source

Ví dụ:

```json
{
  "title": "Backend Developer",
  "company": "ABC Tech",
  "location": "Ho Chi Minh City",
  "salary_min": 15000000,
  "salary_max": 25000000,
  "currency": "VND",
  "level": "Junior",
  "skills": [
    "Java",
    "Spring Boot",
    "PostgreSQL",
    "Docker"
  ],
  "source_url": "https://example.com/jobs/123"
}
```

---

## UC2 — Phát hiện thay đổi

Mỗi lần crawl, hệ thống so sánh dữ liệu với lần trước.

Có thể phát hiện:

- Job mới
- Job bị xóa
- Salary thay đổi
- Description thay đổi
- Skill requirement thay đổi
- Location thay đổi

Ví dụ:

```text
Job #123

Before:
Docker, PostgreSQL

After:
Docker, PostgreSQL, Redis

Change detected:
+ Redis
```

---

## UC3 — AI Skill Extraction

Job Description thường không có structure cố định.

Ví dụ:

```text
We are looking for a Backend Engineer with experience in
Python, FastAPI, Redis, Docker and PostgreSQL.
Knowledge of Kafka is a plus.
```

LLM có thể chuyển thành:

```json
{
  "required_skills": [
    "Python",
    "FastAPI",
    "Redis",
    "Docker",
    "PostgreSQL"
  ],
  "optional_skills": [
    "Kafka"
  ],
  "role": "Backend Engineer",
  "experience_level": "Junior/Mid"
}
```

---

## UC4 — CV Matching

Người dùng upload CV.

Hệ thống:

1. Parse CV.
2. Extract skills.
3. Extract experience.
4. Generate embedding.
5. So sánh với các job.
6. Tính match score.
7. Giải thích vì sao match hoặc không match.

Ví dụ:

```text
Backend Engineer — Company X

Match Score: 82%

Strong matches:
✓ Python
✓ FastAPI
✓ PostgreSQL
✓ Docker

Missing:
✗ Redis
✗ Kafka
✗ Kubernetes
```

---

## UC5 — Skill Trend Analysis

Sau khi crawl được đủ dữ liệu, hệ thống có thể phân tích:

```text
             May   Jun   Jul   Aug

React        31%   34%   35%   33%
Next.js      14%   17%   21%   25%
Docker       39%   43%   47%   52%
Kubernetes   20%   23%   25%   29%
Kafka        12%   14%   18%   20%
```

AI Agent có thể tạo insight:

```text
Docker đang xuất hiện ngày càng nhiều trong các Backend JD.

Next.js có tốc độ tăng nhanh hơn React trong dataset gần đây.

Kubernetes đang dần trở thành kỹ năng phổ biến cho các vị trí Backend Mid-level.
```

---

# 5. Kiến trúc tổng thể

```text
                    ┌────────────────────┐
                    │ Scheduler / Prefect│
                    └─────────┬──────────┘
                              │
                              ▼
                       Planner Agent
                              │
          ┌───────────────────┼───────────────────┐
          ▼                   ▼                   ▼
      Source A             Source B            Source C
      Crawler              Crawler             Crawler
          │                   │                   │
          └───────────────────┼───────────────────┘
                              ▼
                         Raw Job Data
                              │
                              ▼
                     Normalization Layer
                              │
                              ▼
                      Extraction Agent
                              │
                              ▼
                       Validator Agent
                           │       │
                         valid   invalid
                           │       │
                           │     retry
                           ▼
                        Database
                           │
           ┌───────────────┼────────────────┐
           ▼               ▼                ▼
      Analyst Agent    Matcher Agent     Trend Agent
           │               │                │
           └───────────────┼────────────────┘
                           ▼
                       Alert Agent
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
          Dashboard      Telegram      Discord
```

---

# 6. Thiết kế Agentic AI

## 6.1. Planner Agent

Planner Agent quyết định:

- nguồn nào cần crawl,
- nguồn nào nên ưu tiên,
- source nào đang lỗi,
- source nào nên giảm tần suất crawl,
- crawler nào nên được chạy lại.

Ví dụ state:

```json
{
  "source": "company_A",
  "last_success": "2026-08-21T08:00:00",
  "failure_rate": 0.02,
  "new_jobs_last_run": 12,
  "avg_change_rate": 0.18,
  "priority": "high"
}
```

Logic:

```text
Nếu source có nhiều job mới
→ tăng priority

Nếu source ít thay đổi
→ giảm frequency

Nếu source fail liên tục
→ quarantine / retry later
```

---

## 6.2. Extraction Agent

Nhiệm vụ:

- đọc raw HTML / text,
- extract title,
- company,
- salary,
- location,
- experience,
- skills,
- level.

Nên dùng deterministic extraction trước:

```text
JSON-LD
  ↓
CSS Selector
  ↓
XPath
  ↓
LLM fallback
```

Lý do:

- nhanh hơn,
- rẻ hơn,
- dễ debug,
- ít hallucination,
- giảm số lần gọi LLM.

---

## 6.3. Validator / Critic Agent

Dùng để kiểm tra dữ liệu sau extraction.

Ví dụ:

```json
{
  "title": "Software Engineer",
  "salary": "$900000/month",
  "location": null
}
```

Validator có thể phát hiện:

```text
salary anomaly
missing location
invalid currency
unexpected format
```

Workflow:

```text
Extract
   ↓
Validate
   ↓
Invalid?
   ↓ yes
Re-extract
   ↓
Compare with raw data
   ↓
Accept / Reject / NEED_REVIEW
```

Pattern:

```text
Generator
   ↓
Critic
   ↓
Retry
   ↓
Accept / Reject
```

Đây là một phần thể hiện rõ tính Agentic AI.

---

## 6.4. Analyst Agent

Nhiệm vụ:

- phân tích dữ liệu lịch sử,
- tạo insight,
- tìm trend,
- phát hiện thay đổi bất thường.

Ví dụ:

```text
Trong 30 ngày gần nhất:

Docker xuất hiện trong 52% Backend jobs,
tăng 9% so với tháng trước.

Kafka tăng mạnh trong nhóm Mid-level Backend.

Java vẫn chiếm tỷ lệ cao nhất trong Enterprise Backend jobs.
```

---

## 6.5. Matcher Agent

Nhiệm vụ:

- đọc CV,
- extract profile,
- so sánh với job,
- đưa ra match score,
- giải thích missing skills,
- đề xuất skill roadmap.

Ví dụ:

```text
Match Score: 78%

Matched:
Python
FastAPI
PostgreSQL

Missing:
Redis
Kafka

Recommendation:
Ưu tiên học Redis trước Kafka vì Redis xuất hiện nhiều hơn trong nhóm Junior Backend jobs.
```

---

## 6.6. Trend Agent

Nhiệm vụ:

- phân tích theo thời gian,
- so sánh tuần/tháng,
- phát hiện công nghệ tăng/giảm.

Ví dụ:

```text
Python Backend demand: +11%
Node.js Backend demand: +4%
Java Backend demand: -2%
Go Backend demand: +8%
```

---

## 6.7. Alert Agent

Alert Agent có thể gửi thông báo khi:

- có job mới match > 80%,
- có job internship mới,
- có job tại công ty mục tiêu,
- salary đạt mức mong muốn,
- tech stack phù hợp.

Ví dụ:

```text
New Job Found

Backend Intern — XYZ Tech

Match: 87%

Skills:
Python
FastAPI
PostgreSQL

Missing:
Docker

Posted 12 minutes ago.
```

---

# 7. Crawling System

## 7.1. Loại nguồn dữ liệu

Ưu tiên:

- Public career page
- Company career websites
- Public job feeds
- RSS
- Public API
- Static HTML pages
- JSON-LD embedded job data

Không nên thiết kế project xoay quanh:

- bypass CAPTCHA,
- bypass authentication,
- bypass anti-bot,
- scraping dữ liệu private,
- scraping site cấm rõ ràng.

---

## 7.2. Crawler Strategy

Có thể chia crawler thành:

### HTTP crawler

Dùng cho page render server-side.

```text
HTTP Request
   ↓
HTML
   ↓
BeautifulSoup / Parsel
```

### Browser crawler

Dùng cho site dùng JavaScript.

```text
Playwright
   ↓
Render page
   ↓
DOM
   ↓
Extractor
```

---

## 7.3. Crawl Pipeline

```text
Request URL
   ↓
Fetch
   ↓
Parse
   ↓
Extract
   ↓
Normalize
   ↓
Hash
   ↓
Compare
   ↓
Store
```

---

# 8. Deduplication

Một job có thể xuất hiện trên nhiều nguồn.

Ví dụ:

```text
Source A:
Backend Engineer — ABC

Source B:
Backend Developer — ABC Company
```

Có thể duplicate dựa trên:

- company,
- title,
- location,
- description similarity,
- external_id,
- canonical URL.

Tạo fingerprint:

```text
hash(
    normalized_company +
    normalized_title +
    normalized_location
)
```

Có thể kết hợp embedding similarity.

---

# 9. Change Detection

Mỗi job có thể lưu:

```text
first_seen
last_seen
content_hash
status
```

Ví dụ:

```text
first_seen = 2026-08-01
last_seen  = 2026-08-21
status     = active
```

Nếu job không còn xuất hiện:

```text
status = removed
```

Có thể tạo bảng:

```text
job_changes
```

với:

```text
id
job_id
field_name
old_value
new_value
detected_at
```

---

# 10. Database Design

## 10.1. Sources

```text
sources
-------
id
name
base_url
crawl_frequency
priority
last_crawled
last_success
status
created_at
updated_at
```

---

## 10.2. Jobs

```text
jobs
----
id
source_id
external_id
title
company
location
description
salary_min
salary_max
currency
level
experience_min
experience_max
posted_at
first_seen
last_seen
status
source_url
content_hash
created_at
updated_at
```

---

## 10.3. Skills

```text
skills
------
id
name
normalized_name
category
created_at
```

Category có thể là:

```text
language
framework
database
cloud
devops
messaging
testing
AI
other
```

---

## 10.4. Job Skills

```text
job_skills
----------
job_id
skill_id
requirement_type
confidence
created_at
```

`requirement_type`:

```text
required
optional
preferred
```

---

## 10.5. Crawl Runs

```text
crawl_runs
----------
id
source_id
started_at
finished_at
pages_crawled
items_found
items_new
items_updated
items_removed
items_failed
status
error_message
```

---

## 10.6. Agent Runs

```text
agent_runs
----------
id
agent_name
input_data
output_data
model
tokens_in
tokens_out
latency_ms
status
error
created_at
```

---

## 10.7. Job Changes

```text
job_changes
-----------
id
job_id
field_name
old_value
new_value
detected_at
```

---

## 10.8. User Resume

```text
resumes
-------
id
user_id
file_name
raw_text
embedding
created_at
updated_at
```

---

## 10.9. Job Match

```text
job_matches
-----------
id
resume_id
job_id
match_score
skill_score
semantic_score
missing_skills
matched_skills
explanation
created_at
```

---

# 11. Automation

Automation có thể dùng Prefect.

Ví dụ lịch:

```text
00:00
crawl all high-priority sources

06:00
crawl again

12:00
crawl again

18:00
crawl again

23:00
generate daily analytics
```

Workflow:

```text
crawl_sources
      ↓
normalize_jobs
      ↓
deduplicate
      ↓
extract_skills
      ↓
validate_jobs
      ↓
update_database
      ↓
generate_metrics
      ↓
send_alerts
```

---

# 12. Failure Handling

Một production-like project nên xử lý lỗi.

Ví dụ:

```text
Crawler fail
   ↓
Retry 1
   ↓
Retry 2
   ↓
Retry 3
   ↓
Mark source unhealthy
```

Có thể dùng exponential backoff:

```text
1 minute
5 minutes
30 minutes
```

---

# 13. Observability

Các metric nên track:

```text
crawl_success_rate

crawl_duration

pages_per_run

jobs_discovered

new_jobs

updated_jobs

duplicate_jobs

failed_jobs

LLM_tokens

LLM_cost

agent_latency

agent_failure_rate
```

Dashboard monitoring có thể có:

```text
Crawler Health

Source A   HEALTHY
Source B   HEALTHY
Source C   DEGRADED
Source D   ERROR
```

---

# 14. AI Cost Optimization

Không nên gửi toàn bộ data qua LLM.

Pipeline tốt hơn:

```text
Deterministic parser
       ↓
schema complete?
       ↓
      yes
       ↓
store
```

Nếu thiếu:

```text
schema incomplete
       ↓
LLM extraction
```

Có thể cache kết quả theo:

```text
content_hash
```

Nếu JD không đổi:

```text
skip LLM
```

---

# 15. Embedding và Vector Search

Có thể dùng PostgreSQL + pgvector.

Job description:

```text
description
    ↓
embedding model
    ↓
vector
```

CV:

```text
resume
    ↓
embedding model
    ↓
vector
```

Sau đó:

```text
CV vector
   ↓
cosine similarity
   ↓
Top K jobs
```

Không nhất thiết cần Pinecone hoặc Qdrant ngay từ MVP.

---

# 16. Match Score

Có thể thiết kế custom score:

```text
match_score =
    0.40 * skill_match
  + 0.25 * semantic_similarity
  + 0.15 * experience_match
  + 0.10 * location_match
  + 0.10 * level_match
```

Ví dụ:

```text
skill_match        = 0.85
semantic_similarity = 0.79
experience_match   = 1.00
location_match     = 1.00
level_match        = 0.80
```

Result:

```text
match_score ≈ 86%
```

---

# 17. Dashboard

Frontend có thể dùng Next.js.

## Trang Home

Hiển thị:

```text
Total Jobs

New Jobs Today

Active Companies

Top Skills

Crawler Health
```

---

## Trang Job Explorer

Filter:

- Role
- Location
- Level
- Company
- Skill
- Salary
- Date

---

## Trang Skill Analytics

Charts:

```text
Top Programming Languages

Top Backend Frameworks

Top Frontend Frameworks

Top Databases

Top DevOps Skills

Fastest Growing Skills
```

---

## Trang Job Detail

Hiển thị:

```text
Job Title

Company

Salary

Location

Required Skills

Optional Skills

AI Summary

Source URL
```

---

## Trang CV Match

```text
Resume Match Overview

Top Matching Jobs

Missing Skills

Recommended Learning Path
```

---

## Trang Crawler Monitoring

```text
Source Health

Last Crawl

Next Crawl

Jobs Found

Failure Rate

Average Duration
```

---

# 18. Tech Stack đề xuất

## Backend

```text
Python
FastAPI
Pydantic
SQLAlchemy
```

## Crawling

```text
Crawlee
Playwright
BeautifulSoup
Parsel
```

## Agentic AI

```text
LangGraph
OpenAI / Gemini / Local LLM
```

## Automation

```text
Prefect
```

## Database

```text
PostgreSQL
pgvector
```

## Queue / Cache

```text
Redis
```

## Frontend

```text
Next.js
TypeScript
TailwindCSS
Recharts
```

## DevOps

```text
Docker
Docker Compose
GitHub Actions
```

## Deployment

Một trong các lựa chọn:

```text
Render
Railway
Fly.io
AWS
VPS
```

---

# 19. Folder Structure

Ví dụ:

```text
devradar/
│
├── apps/
│   ├── api/
│   │   ├── main.py
│   │   ├── routes/
│   │   ├── services/
│   │   └── dependencies/
│   │
│   ├── crawler/
│   │   ├── spiders/
│   │   ├── parsers/
│   │   ├── normalization/
│   │   └── pipeline/
│   │
│   ├── agent/
│   │   ├── graph.py
│   │   ├── state.py
│   │   ├── nodes/
│   │   │   ├── planner.py
│   │   │   ├── extractor.py
│   │   │   ├── validator.py
│   │   │   ├── analyst.py
│   │   │   ├── matcher.py
│   │   │   └── alert.py
│   │   └── tools/
│   │
│   └── web/
│
├── core/
│   ├── config/
│   ├── database/
│   ├── models/
│   ├── schemas/
│   └── utils/
│
├── flows/
│   ├── crawl_flow.py
│   ├── analysis_flow.py
│   └── daily_report_flow.py
│
├── tests/
│
├── docker/
│
├── scripts/
│
├── docs/
│
├── docker-compose.yml
├── pyproject.toml
├── .env.example
└── README.md
```

---

# 20. LangGraph Flow

Agent state:

```python
class AgentState:
    source_id: str
    raw_jobs: list
    normalized_jobs: list
    validation_errors: list
    retry_count: int
    status: str
```

Flow:

```text
START
  ↓
Planner
  ↓
Crawler Tool
  ↓
Normalizer
  ↓
Extractor
  ↓
Validator
  ↓
Is Valid?
 ┌───────┴────────┐
 │                │
yes              no
 │                │
Store         retry_count < 3?
 │                │
 │              yes
 │                │
 │            Extractor
 │
 ▼
Analyst
 │
 ▼
Matcher
 │
 ▼
Alert
 │
 ▼
END
```

---

# 21. API Design

Một số endpoint:

```text
GET /jobs

GET /jobs/{id}

GET /jobs/trending

GET /skills

GET /skills/trending

GET /companies

POST /resume

GET /resume/{id}/matches

GET /crawler/sources

GET /crawler/runs

POST /crawler/run

GET /agents/runs
```

---

# 22. Security

Cần lưu ý:

```text
rate limiting

input validation

file upload validation

environment secrets

SQL injection prevention

API authentication

safe HTML parsing

request timeout

URL allow-list
```

Nếu cho crawler nhận URL từ user thì phải cẩn thận SSRF.

---

# 23. Testing

## Unit Test

Test:

```text
normalizer

parser

salary extraction

skill mapping

deduplication

match scoring
```

## Integration Test

```text
crawler → database

agent → database

API → database

resume → matching
```

## Agent Test

Test:

```text
invalid salary

missing fields

unexpected HTML

LLM malformed JSON

timeout

retry logic
```

---

# 24. Dataset

Ban đầu có thể crawl:

```text
3-5 sources
```

Mục tiêu MVP:

```text
500 - 3000 jobs
```

Sau đó tăng lên:

```text
5000+
```

Dataset càng lớn thì phần trend analysis càng có giá trị.

---

# 25. Roadmap phát triển

## Version 1 — Crawler MVP

Mục tiêu:

```text
Crawler
   ↓
Normalize
   ↓
PostgreSQL
```

Features:

- crawl 3 sources,
- lưu jobs,
- deduplicate,
- logging,
- simple REST API.

---

## Version 2 — Automation

Thêm:

```text
Prefect

scheduled crawling

retry

crawl history

change detection

crawler health
```

---

## Version 3 — AI

Thêm:

```text
LLM extraction

skill extraction

job classification

AI summary

embedding

semantic search
```

---

## Version 4 — Agentic AI

Thêm LangGraph:

```text
Planner Agent

Extraction Agent

Validator Agent

Analyst Agent

Matcher Agent

Alert Agent
```

---

## Version 5 — Dashboard

Thêm:

```text
Next.js

analytics dashboard

job explorer

skill trends

CV matcher

crawler monitoring
```

---

## Version 6 — Production-like Features

Thêm:

```text
Redis queue

distributed workers

CI/CD

monitoring

LLM cost tracking

rate limiting

user authentication
```

---

# 26. Lộ trình 8 tuần

## Tuần 1

- Setup project
- PostgreSQL
- FastAPI
- Job schema
- Source schema

## Tuần 2

- Crawler source #1
- Crawler source #2
- Normalization

## Tuần 3

- Crawler source #3
- Deduplication
- Change detection

## Tuần 4

- Prefect
- Scheduler
- Retry
- Crawl monitoring

## Tuần 5

- LLM extraction
- Skill extraction
- Job classification

## Tuần 6

- LangGraph
- Validator Agent
- Planner Agent
- Analyst Agent

## Tuần 7

- Resume parsing
- pgvector
- Match scoring
- Matcher Agent

## Tuần 8

- Dashboard
- Docker
- Deployment
- README
- Demo video
- CV bullet points

---

# 27. Những điểm nên demo khi phỏng vấn

## Demo 1

Trigger crawler:

```text
crawl source
```

Hiển thị:

```text
153 jobs found
18 new
7 updated
2 removed
```

## Demo 2

Cho xem một Job Description raw.

Sau đó cho xem structured data do AI extract.

## Demo 3

Tạo một JD có dữ liệu lỗi.

Cho Validator Agent phát hiện và retry.

## Demo 4

Upload CV.

Hiển thị:

```text
Top 10 matching jobs
```

## Demo 5

Cho xem dashboard:

```text
Top skills this month
```

## Demo 6

Cho xem crawler monitoring.

Ví dụ:

```text
Source A HEALTHY
Source B DEGRADED
Source C FAILED
```

---

# 28. Điểm mạnh khi đưa vào CV

Project này thể hiện được nhiều kỹ năng:

## Software Engineering

- clean architecture,
- modular design,
- testing,
- error handling.

## Backend

- REST API,
- database,
- async processing.

## Data Engineering

- ingestion,
- normalization,
- deduplication,
- change detection.

## Web Crawling

- HTTP parsing,
- browser automation,
- retry,
- throttling.

## AI

- structured extraction,
- embeddings,
- semantic search,
- LLM evaluation.

## Agentic AI

- planner,
- tools,
- state,
- validation,
- retry,
- decision making.

## DevOps

- Docker,
- CI/CD,
- deployment,
- monitoring.

---

# 29. Cách ghi trên CV

## Project Name

**DevRadar — Agentic Job Market Intelligence Platform**

## Description

```text
Built an agentic AI job-market intelligence platform that
periodically crawls public job sources, normalizes and
deduplicates listings, extracts technical skills using
LLM-based structured extraction, analyzes hiring trends,
and semantically matches job descriptions against resumes.
```

## Tech Stack

```text
Python
FastAPI
Crawlee
Playwright
LangGraph
Prefect
PostgreSQL
pgvector
Redis
Next.js
Docker
GitHub Actions
```

---

# 30. CV Bullet Points mẫu

```text
• Designed and implemented an automated job data ingestion
  pipeline that periodically crawls multiple public career
  sources and performs normalization, deduplication and
  change detection.

• Built a LangGraph-based agentic workflow consisting of
  planner, extraction, validation and analysis agents with
  retry and error recovery logic.

• Integrated LLM-based structured extraction to identify
  required skills, experience levels and job metadata from
  unstructured job descriptions.

• Implemented semantic job-resume matching using PostgreSQL
  and pgvector embeddings.

• Developed a recruitment analytics dashboard for tracking
  trending technologies, job demand and crawler health.

• Containerized the platform with Docker and automated
  scheduled workflows using Prefect.
```

---

# 31. Những câu interviewer có thể hỏi

## Crawling

```text
How do you avoid duplicate jobs?

How do you handle JavaScript websites?

What happens when the site changes HTML?

How do you handle crawler failures?

How do you respect rate limits?
```

## Backend

```text
Why PostgreSQL?

How do you design your schema?

How do you scale the crawler?

How do you handle concurrent writes?
```

## AI

```text
Why use LLM here?

Why not use regex?

How do you prevent hallucination?

How do you evaluate extraction quality?

How do you control token cost?
```

## Agent

```text
Why does this need an agent?

What makes this system agentic?

How does your planner make decisions?

How do agents share state?

What happens if an agent fails?
```

## System Design

```text
How would you scale to 100 sources?

How would you process 1 million jobs?

How would you design a queue?

How would you monitor the system?
```

---

# 32. Câu trả lời quan trọng: "Tại sao cần Agent?"

Không nên trả lời:

```text
Because AI Agent is trending.
```

Nên trả lời:

```text
The crawler and deterministic pipeline handle predictable
tasks, while agents are only used for tasks that require
reasoning or adaptive decision-making.

For example, the planner agent prioritizes unstable or
high-change sources, while the validator agent evaluates
low-confidence extraction results and decides whether to
retry, accept or flag them for review.
```

Điều này thể hiện bạn hiểu Agentic AI, thay vì chỉ gắn LLM vào project.

---

# 33. Những thứ không nên over-engineer ở MVP

Không cần ngay:

```text
Kubernetes

Kafka

Microservices

Pinecone

10+ agents

20 data sources
```

Với project cá nhân, một monolith modular tốt thường hợp lý hơn.

MVP nên ưu tiên:

```text
Python

FastAPI

PostgreSQL

Crawlee / Playwright

Prefect

LangGraph

Next.js

Docker
```

Sau đó mới scale.

---

# 34. Một kiến trúc MVP thực tế

```text
              Next.js
                 │
                 ▼
              FastAPI
                 │
        ┌────────┼────────┐
        ▼        ▼        ▼
   PostgreSQL   Redis   LangGraph
        ▲                 │
        │                 │
        └──── Prefect ────┘
                 │
                 ▼
              Crawlers
                 │
                 ▼
          Public Job Sources
```

Tất cả có thể chạy bằng:

```text
docker-compose
```

---

# 35. Feature nâng cao

Sau khi MVP xong, có thể thêm:

## AI Career Advisor

Dựa vào CV + job market:

```text
Your current profile:
Python Backend

Most valuable missing skills:
1. Docker
2. Redis
3. AWS
4. Kafka
```

---

## Company Watchlist

User chọn:

```text
Google
Shopee
Grab
VNG
FPT
```

Hệ thống theo dõi job mới.

---

## Salary Analytics

```text
Backend Junior

Median salary:
18M

Top 25%:
25M+

Most valuable skills:
AWS
Kafka
Kubernetes
```

---

## Skill Graph

Tạo graph:

```text
Python
 ├── FastAPI
 ├── Django
 ├── PostgreSQL
 └── Docker

Java
 ├── Spring Boot
 ├── Kafka
 └── Kubernetes
```

---

## Tech Stack Recommendation

User chọn:

```text
Goal:
Backend Developer
```

AI trả:

```text
Recommended learning path:

Python
↓
FastAPI
↓
PostgreSQL
↓
Redis
↓
Docker
↓
AWS
```

Dựa trên dữ liệu tuyển dụng thực tế.

---

# 36. Tiêu chí project hoàn thành tốt

Project đủ mạnh để đưa CV khi có:

- 3+ nguồn dữ liệu thực tế
- 1000+ job records
- scheduled crawling
- deduplication
- change detection
- crawler monitoring
- LLM structured extraction
- LangGraph workflow
- CV matching
- trend analytics
- dashboard
- Docker
- deployed demo
- README tốt
- architecture diagram
- demo video

---

# 37. Kết luận

DevRadar phù hợp với một sinh viên IT năm 4 vì nó kết hợp được nhiều mảng quan trọng trong một project duy nhất:

```text
Web Crawling
+
Backend
+
Database
+
Automation
+
AI
+
Agentic AI
+
Data Engineering
+
System Design
+
DevOps
```

Điểm quan trọng nhất là không biến project thành:

```text
crawler
  ↓
GPT
  ↓
output
```

Mà nên biến nó thành:

```text
Automated Data Platform
        +
Agentic Decision Layer
        +
Job Market Intelligence
```

Nếu triển khai tốt, đây có thể trở thành project nổi bật nhất trong CV và cũng là một project rất tốt để dùng trong các buổi phỏng vấn Backend, AI Engineer, Data Engineer hoặc Software Engineer.

---

# 38. Next Step đề xuất

Bước tiếp theo nên làm là thiết kế chi tiết cho **Version 1**:

1. Chốt 3 nguồn dữ liệu.
2. Thiết kế ERD PostgreSQL.
3. Thiết kế crawler interface.
4. Setup FastAPI.
5. Setup Docker Compose.
6. Viết crawler đầu tiên.
7. Lưu được 100-500 job đầu tiên.
8. Sau khi data pipeline ổn mới thêm LangGraph và LLM.

Nguyên tắc quan trọng:

> **Data pipeline trước, Agent sau.**

Một agent mạnh nhưng không có data pipeline ổn định sẽ làm project khó debug và khó mở rộng.
