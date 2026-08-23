# V6-011 — GitHub incident alerting design

**Trạng thái:** Accepted
**Ngày:** 2026-08-23

## Mục tiêu

Dùng hạ tầng GitHub hiện có để route CI incident thật tới issue được assign cho repository owner, đồng
thời cung cấp một manual drill không cần tạo failure giả trong CI chính. Capability này đóng phần
operational CI alert routing của V6-005; nó không chứng minh public uptime, HTTPS ingress hoặc backup
off-host.

## Context và lựa chọn

Repository đã bật GitHub Issues, owner là `HPhucTV`, CI chạy trên GitHub Actions và không có Discord
webhook/monitoring provider secret. Ba hướng được cân nhắc:

1. **GitHub Issues từ Actions — chọn.** Không thêm provider hoặc secret, có assignee, URL, timestamp và
   audit trail thật. Giới hạn: chỉ quan sát CI, không quan sát endpoint public.
2. Discord webhook. Tái sử dụng channel concept V5 nhưng cần webhook secret và external account chưa có.
3. Monitoring SaaS/email. Có uptime/escalation tốt hơn nhưng cần provider/account mới và chỉ có ý nghĩa
   sau khi tồn tại public URL.

## Workflow contract

Tạo `.github/workflows/incident-alert.yml` với hai trigger:

- `workflow_run` theo dõi workflow `DevRadar CI`, branch `main`, activity `completed`;
- `workflow_dispatch` tạo một issue drill có nhãn rõ trong title/body.

Job chỉ chạy khi manual dispatch hoặc khi một push CI trên `main` kết thúc với `failure`, `cancelled`,
`timed_out` hoặc `action_required`. Mỗi terminal run/attempt là một incident riêng; workflow không gộp
hai failure khác nhau.

Workflow dùng GitHub CLI đã cài sẵn trên hosted runner và `GITHUB_TOKEN`, với quyền tối thiểu
`contents: read` và `issues: write`. Issue được assign cho `github.repository_owner` và chỉ chứa metadata
an toàn: workflow/run ID, conclusion, event, SHA và GitHub run URL. Không chứa log, artifact, environment,
secret hoặc payload ứng dụng.

## Trust boundary và failure behavior

`workflow_run` có thể nhận write token dù workflow trước không có. Vì vậy alert workflow tuyệt đối không
checkout code, download artifact, restore cache hoặc thực thi dữ liệu từ workflow trước; nó chỉ đọc các
field scalar trong event payload và gọi `gh issue create`. Nếu issue creation thất bại, workflow phải fail
để sự cố routing hiện rõ trong Actions, không swallow lỗi.

Official references:

- https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#workflow_run
- https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-github-cli
- https://docs.github.com/en/actions/tutorials/authenticate-with-github_token
- https://docs.github.com/en/rest/issues/issues#create-an-issue

## Verification và evidence

1. Static contract test phải fail khi workflow chưa tồn tại, rồi pass sau implementation.
2. Full default/static gates không được regression.
3. Push workflow lên `main`, chờ CI required checks terminal.
4. Dispatch workflow thật qua GitHub API, xác nhận run `success`.
5. Xác nhận issue được tạo bởi `github-actions[bot]`, assign `HPhucTV`, body chỉ có safe metadata; sau đó
   đóng drill issue với state reason `completed`.
6. Ghi run/issue URL vào evidence. V6-005 vẫn `In Progress` vì public uptime và off-host backup còn thiếu.
