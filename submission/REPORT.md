# Báo cáo cá nhân — K4-L3A Day 13 Monitoring & LLMOps

> Mỗi học viên hoàn thiện một file duy nhất này. Khi dẫn evidence, dùng đường dẫn tương đối, ví dụ `evidence/07-trace-waterfall.png`.

## 1. Thông tin học viên

- **Họ và tên:** Đỗ Thanh Tùng
- **MSSV:** 2A202602845
- **Lớp:** K4-L3A
- **Repository URL:** https://github.com/tungne1311/K4-L3-DAY13-DoThanhTung-2A202602845-Monitoring-LLMOps
- **Commit SHA cuối:**
- **Challenge ID:**
- **Tên project Langfuse cá nhân:** `day13-k4-l3a-2A202602845`

## 2. Evidence index

Điền đúng đường dẫn tới evidence thực tế. Có thể đổi tên hoặc dùng nhiều ảnh nếu cần.

| Evidence | Đường dẫn |
|---|---|
| Baseline CP0 (validators, pytest, metrics) | `evidence/00-baseline.txt` |
| Pytest cuối | `evidence/01-pytest.png` |
| Log validator | `evidence/02-log-validator.png`, `evidence/02-log-validator.txt` |
| Dashboard validator | `evidence/03-dashboard-validator.png` |
| Structured log | `evidence/04-structured-log.png`, `evidence/04-structured-log.txt` |
| PII redaction | `evidence/05-pii-redaction.png`, `evidence/05-pii-redaction.txt` |
| Trace list | `evidence/06-trace-list.png` |
| Trace waterfall | `evidence/07-trace-waterfall.png` |
| Trace metadata | `evidence/08-trace-metadata.png` |
| Prompt versions | `evidence/09-prompt-versions.png` |
| Prompt rollback | `evidence/10-prompt-rollback.png` |
| Dashboard runtime | `evidence/11-dashboard-overview.png` |
| Incident metric | `evidence/12-incident-metric.png` |
| Incident log | `evidence/13-incident-log.png` |
| Incident trace | `evidence/14-incident-trace.png` |

## 3. Kết quả kỹ thuật

| Nội dung | Baseline | Kết quả cuối | Nhận xét |
|---|---|---|---|
| `validate_logs.py` | 30/100 — 22 records, 20 thiếu required fields, 20 thiếu enrichment, 0 correlation ID | | Baseline chưa làm TODO CP1; PII "passed" chỉ vì log chưa ghi PII thô |
| `validate_dashboard.py` | 6/6 panel có trong contract | | Validator chỉ kiểm contract, chưa có dashboard runtime |
| `pytest` | 22 passed | | |
| Số traces hợp lệ | 10 traces `day13-agent-request`, chỉ có root `lab-agent-run` | | Chưa có child retrieval/generation; `prompt_source=local-fallback` vì chưa tạo prompt `day13-chat` |
| Số PII leak | 0 | | |
| Latency P95 / TTFT P95 | 2825 ms / 50 ms (P50 672 ms, P99 2825 ms) | | Chỉ 10 request nên P95 = P99 = request chậm nhất |
| Retrieval success rate | 100% (10/10) | | |

## 4. Logging và PII

- **Cách tạo/nhận và truyền correlation ID:** `CorrelationIdMiddleware` (`app/middleware.py`) gọi `clear_contextvars()` đầu mỗi request để không dính context của request trước. Nếu header `x-request-id` đúng format `req-<8-hex>` thì dùng lại, còn lại (thiếu hoặc sai format, ví dụ chứa ký tự xuống dòng) thì sinh mới `req-` + 8 ký tự hex từ `uuid4`. ID được `bind_contextvars` nên mọi log trong request tự có `correlation_id`; đồng thời lưu ở `request.state` để truyền vào `LabAgent.run` → trace metadata, và trả về client qua header `x-request-id`, `x-response-time-ms` và field `correlation_id` trong body.
- **Các metadata được ghi vào structured log:** `ts`, `level`, `service`, `event`, `correlation_id`, và context bind ngay đầu `/chat` trước `request_received`: `user_id_hash` (SHA-256 cắt 12 ký tự, không ghi user_id thô), `session_id`, `feature`, `model`, `env`. Log `response_sent` có thêm `latency_ms`, `ttft_ms`, `tokens_in/out`, `cost_usd`, `quality_score`, `tool_name`, `tool_success`.
- **Cách bảo đảm PII được scrub trước khi ghi:** processor `scrub_event` được đăng ký trong chuỗi structlog **trước** `JsonlFileProcessor` và `JSONRenderer`, nên dữ liệu bị che trước khi serialize/ghi file. Processor duyệt đệ quy mọi field string (không chỉ `payload`), gồm cả dict/list lồng nhau. Pattern trong `app/pii.py`: email, thẻ thanh toán, CCCD 12 số, SĐT Việt Nam (`0…`/`+84…`, có dấu cách/chấm/gạch), hộ chiếu (`B1234567`). Thứ tự áp dụng: email trước để email chứa số không bị che dở dang, rồi chuỗi số dài (thẻ, CCCD) trước SĐT.
- **Cách kiểm chứng kết quả:** baseline `validate_logs.py` = 30/100 (`evidence/00-baseline.txt`); sau khi xóa log cũ, restart API và chạy lại `load_test.py` → **100/100**, 0 thiếu field, 0 thiếu enrichment, ≥10 correlation ID duy nhất, 0 PII leak (`evidence/02-log-validator.txt`). Grep log không còn email/SĐT/thẻ/CCCD/passport giả nào (`evidence/05-pii-redaction.txt`). Test tự động: `tests/test_pii.py` (email, SĐT, CCCD, thẻ, passport, scrub đệ quy) và `tests/test_correlation_id.py` (sinh ID, dùng lại ID hợp lệ, từ chối ID sai, log API đủ enrichment và không có PII) — `pytest` 30 passed.

## 5. Tracing và prompt versioning

- **Cách xác nhận traces do chính tôi tạo trong project cá nhân:**
- **Cấu trúc root/retrieval/generation observations:**
- **Cách nối trace với log:**
- **Prompt name:**
- **Version/label baseline:**
- **Version/label candidate:**
- **Trace ID của mỗi version:**
- **Cách promote và rollback `production`:**

## 6. Dashboard, SLO và alerts

- **Dashboard và sáu panel:**
- **SLO và lý do chọn:**
- **Cách tính error budget:**
- **Ba alert và runbook tương ứng:**

## 7. Điều tra challenge

- **Challenge ID:**
- **Khoảng thời gian điều tra:**
- **Triệu chứng từ metrics:**
- **Log line và correlation ID liên quan:**
- **Trace ID và span gây ảnh hưởng:**
- **Root cause:**
- **Fix action:**
- **Preventive measure:**

## 8. Giải thích và tự đánh giá

- **Một quyết định kỹ thuật quan trọng và lý do:**
- **Một lỗi/blocker đã gặp:**
- **Cách tìm nguyên nhân và xử lý:**
- **Cách hiểu luồng Metrics → Logs → Traces:**
- **Vai trò của prompt version, token/cost, SLO hoặc rollback trong vận hành LLM:**
- **Điều quan trọng nhất đã học:**
- **Hạn chế hoặc phần chưa hoàn thành, nếu có:**

## 9. Checklist trước khi nộp

- [ ] Kết quả và evidence thuộc commit SHA cuối.
- [ ] Tất cả ảnh/output mở được bằng đường dẫn tương đối.
- [ ] Incident evidence nối đúng metric → log → trace.
- [ ] Trace/prompt evidence thuộc project Langfuse cá nhân và ảnh không lộ key/secret.
- [ ] Repository chạy lại được theo README.
- [ ] Không có secret, API key, PII thô hoặc evidence của người khác/lớp khác.
- [ ] URL repo và commit SHA cuối đã được nộp trên LMS/Codelabs.
