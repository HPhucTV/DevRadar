# Runbook: Incident response

## Phân loại nhanh

| Symptom | First action | Runbook |
|---|---|---|
| Health unavailable/latency vượt ngưỡng | Chạy monitor, kiểm tra container/log correlation | deploy/rollback |
| Migration/deploy fail | Dừng rollout, giữ image cũ, không downgrade mù | deploy/rollback |
| Data loss/corruption suspicion | Freeze mutation, preserve evidence, restore isolated | backup/restore |
| CV/secret exposure | Revoke/rotate secret, restrict access, preserve safe IDs only | security incident |
| Source terms/anti-bot change | Pause source, không bypass control, review allow-list | ingestion/source policy |

## Quy tắc evidence

- Mỗi incident có ID, thời gian, impact, affected source/data, containment và recovery evidence.
- Log chỉ dùng request/run/source/job opaque IDs, status và bounded error code; không đính kèm raw JD/CV,
  cookie, token, webhook, password, database URL hoặc full provider prompt.
- Chỉ đóng incident sau khi monitor, smoke, backup/restore hoặc replay test tương ứng đã có output cuối.
