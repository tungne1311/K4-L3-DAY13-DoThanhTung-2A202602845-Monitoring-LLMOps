# Alert và Runbook

Mỗi alert dựa trên triệu chứng người dùng thấy (chậm, lỗi, tốn tiền) hoặc SLO, không dựa trực tiếp vào tên implementation nội bộ. Định nghĩa máy đọc được nằm trong [`../config/alert_rules.yaml`](../config/alert_rules.yaml), SLO trong [`../config/slo.yaml`](../config/slo.yaml). Dashboard: `python scripts/dashboard.py` → <http://127.0.0.1:8050>.

Quy trình chung cho mọi alert: **Metrics → Logs → Traces**. Xác định khoảng thời gian trên dashboard, lọc `data/logs.jsonl` lấy `correlation_id` của request bất thường, mở trace có cùng `correlation_id` trên Langfuse (Tracing → filter Metadata `correlation_id`) và so sánh span `retrieve`, `resolve-prompt`, `llm-generate`.

## Alert 1

- Tên: `HighLatencyP95`
- Severity: P2-warning
- Duration: 5m
- Kênh thông báo: Slack `#day13-k4-l3a-alerts`
- SLI/SLO liên quan: `fast_successful_requests` — 99.5% request thành công trong ≤ 2000 ms (28 ngày)
- Điều kiện và thời gian duy trì: P95 `latency_ms` của `response_sent` > 2000 ms liên tục 5 phút (ngưỡng SLO; baseline warm P95 ≈ 153 ms, cold prompt fetch 1.2–1.9 s, rag_slow ≈ 2.65 s)
- Ảnh hưởng tới người dùng: phần lớn câu trả lời chậm hơn 2 giây; mỗi request chậm tiêu error budget của SLO
- Ba bước kiểm tra đầu tiên:
  1. Dashboard panel *Latency percentiles and TTFT*: P95 tăng cùng lúc với TTFT hay không. TTFT bình thường (~50 ms) mà latency tăng → chậm nằm trước/ngoài bước sinh token.
  2. Lọc log chậm: `Select-String -Path data\logs.jsonl -Pattern '"response_sent"' | ?{ ($_.Line | ConvertFrom-Json).latency_ms -gt 2000 }`, lấy `correlation_id`.
  3. Mở trace cùng `correlation_id`: so thời lượng `retrieve` (vector store), `resolve-prompt` (Langfuse prompt fetch) và `llm-generate` để biết span nào chiếm thời gian.
- Mitigation tạm thời: nếu `retrieve` chậm → giảm tải hoặc chuyển sang corpus/fallback cache; nếu `resolve-prompt` chậm → tăng `cache_ttl_seconds` hoặc dùng fallback prompt local; nếu `llm-generate` chậm → chuyển model nhẹ hơn. Tắt incident practice nếu đang bật (`python scripts/inject_incident.py --scenario rag_slow --disable`).
- Owner: Đỗ Thanh Tùng (on-call)

## Alert 2

- Tên: `HighErrorRate`
- Severity: P1-critical
- Duration: 5m
- Kênh thông báo: Slack `#day13-k4-l3a-alerts`
- SLI/SLO liên quan: `fast_successful_requests` (request lỗi là bad event); guardrail `error_rate_pct_max: 2`, `retrieval_success_rate_pct_min: 90`
- Điều kiện và thời gian duy trì: error rate (`request_failed` / `request_received`) > 2% **hoặc** retrieval success < 90% liên tục 5 phút. Error rate 2% là burn rate 4 (hết budget 28 ngày trong 7 ngày).
- Ảnh hưởng tới người dùng: người dùng nhận HTTP 500, không có câu trả lời
- Ba bước kiểm tra đầu tiên:
  1. Dashboard panel *Error rate and retrieval success*: xem `count_by_value` để biết `error_type` nào tăng và retrieval success có giảm cùng lúc không.
  2. Lọc `event == "request_failed"` trong log, đọc `error_type`, `payload.detail`, `tool_name`, `tool_success` và lấy `correlation_id`.
  3. Mở trace cùng `correlation_id`: span `retrieve` có level ERROR và `status_message` (ví dụ `RuntimeError: Vector store timeout`) cho biết lỗi nằm ở dependency nào.
- Mitigation tạm thời: lỗi ở vector store → trả câu trả lời fallback thay vì 500, bật retry có giới hạn hoặc chuyển sang index dự phòng; lỗi sau khi đổi prompt/model → rollback label `production` về version ổn định (`python scripts/manage_prompt.py promote --version <N>`). Tắt incident practice nếu đang bật (`--scenario tool_fail --disable`).
- Owner: Đỗ Thanh Tùng (on-call)

## Alert 3

- Tên: `CostPerRequestSpike`
- Severity: P3-warning
- Duration: 15m
- Kênh thông báo: Slack `#day13-k4-l3a-alerts`
- SLI/SLO liên quan: guardrail `daily_cost_usd_max: 2.5`; baseline chi phí ≈ 0.0019 USD/request, ngưỡng 0.004 USD ≈ 2× baseline
- Điều kiện và thời gian duy trì: trung bình `cost_usd` mỗi `response_sent` > 0.004 USD liên tục 15 phút (chờ lâu hơn vì chi phí không làm hỏng trải nghiệm ngay, tránh báo nhầm khi có vài câu hỏi dài)
- Ảnh hưởng tới người dùng: chưa lỗi ngay nhưng tiêu nhanh ngân sách ngày; nếu kéo dài có thể phải chặn traffic khi chạm 2.5 USD/ngày. Câu trả lời dài bất thường cũng làm đọc chậm hơn.
- Ba bước kiểm tra đầu tiên:
  1. Dashboard panel *Cost over time* và *Input and output tokens*: chi phí tăng do `tokens_out` hay `tokens_in`.
  2. Lọc `response_sent` có `cost_usd` cao nhất trong log, lấy `correlation_id`, so `feature` và `model`.
  3. Mở trace cùng `correlation_id`: generation `llm-generate` cho biết `usage` input/output, `cost` và prompt version đang dùng; so với trace baseline cùng input.
- Mitigation tạm thời: output token tăng → giới hạn `max_tokens` hoặc rollback prompt về version ngắn hơn; input token tăng → kiểm tra prompt/docs mới được gắn label `production`; chuyển feature tốn kém sang model rẻ hơn. Tắt incident practice nếu đang bật (`--scenario cost_spike --disable`).
- Owner: Đỗ Thanh Tùng (on-call)
