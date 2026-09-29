# Báo cáo cá nhân — K4-L3A Day 13 Monitoring & LLMOps

> Mỗi học viên hoàn thiện một file duy nhất này. Khi dẫn evidence, dùng đường dẫn tương đối, ví dụ `evidence/07-trace-waterfall.png`.

## 1. Thông tin học viên

- **Họ và tên:** Đỗ Thanh Tùng
- **MSSV:** 2A202602845
- **Lớp:** K4-L3A
- **Repository URL:** https://github.com/tungne1311/K4-L3-DAY13-DoThanhTung-2A202602845-Monitoring-LLMOps
- **Commit SHA cuối:**
- **Challenge ID:** `day13-k4-l3a-monitoring-llmops-v1` (cohort K4, seed 1311)
- **Tên project Langfuse cá nhân:** `day13-k4-l3a-2A202602845`

## 2. Evidence index

Điền đúng đường dẫn tới evidence thực tế. Có thể đổi tên hoặc dùng nhiều ảnh nếu cần.

| Evidence | Đường dẫn |
|---|---|
| Baseline CP0 (validators, pytest, metrics) | `evidence/00-baseline.txt` |
| Pytest cuối | `evidence/01-pytest.png` |
| Log validator | `evidence/02-log-validator.png`, `evidence/02-log-validator.txt` |
| Dashboard validator | `evidence/03-dashboard-validator.png`, `evidence/03-dashboard-validator.txt` |
| Structured log | `evidence/04-structured-log.png`, `evidence/04-structured-log.txt` |
| PII redaction | `evidence/05-pii-redaction.png`, `evidence/05-pii-redaction.txt` |
| Trace list | `evidence/06-trace-list.png`, `evidence/06-trace-list.txt` |
| Trace waterfall | `evidence/07-trace-waterfall.png` |
| Trace metadata | `evidence/08-trace-metadata.png` |
| Prompt versions | `evidence/09-prompt-versions.png` |
| Prompt rollback | `evidence/10-prompt-rollback.png`, `evidence/10-prompt-rollback.txt` |
| Dashboard runtime | `evidence/11-dashboard-overview.png` |
| Incident metric | `evidence/12-incident-metric.png`, `evidence/12b-incident-metric-60m.png`, `evidence/12-incident-run.txt` |
| Incident log | `evidence/13-incident-log.png`, `evidence/13-incident-log.txt` |
| Incident trace | `evidence/14-incident-trace.png`, `evidence/14b-incident-trace-metadata.png` |

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

- **Cách xác nhận traces do chính tôi tạo trong project cá nhân:** key trong `.env` thuộc project cá nhân `day13-k4-l3a-2A202602845` (project id `cmumdhy8720jiad0c945kvqcu`). Traces được sinh từ `load_test.py --concurrency 5` và các request prompt chạy trên máy tôi. Mỗi trace có `correlation_id` trùng với một dòng log trong `data/logs.jsonl` của tôi. 36 traces có đủ root + retrieval + generation (`evidence/06-trace-list.txt`, `evidence/06-trace-list.png`).
- **Cấu trúc root/retrieval/generation observations:** root `lab-agent-run` (AGENT, `@observe`, không capture input/output thô) có 3 con tạo bằng `start_as_current_observation` của SDK v4 (`app/agent.py`, `app/tracing.py`):
  - `retrieve` (RETRIEVER): input là query preview đã scrub, output là số lượng và nội dung docs; khi vector store lỗi thì level ERROR kèm `status_message`.
  - `resolve-prompt` (SPAN): thời gian lấy prompt từ Langfuse, output gồm name/label/version/source; level WARNING nếu phải fallback.
  - `llm-generate` (GENERATION): `model=claude-sonnet-4-5`, input là prompt đã scrub PII, link tới prompt managed, `usage_details` input/output, `cost_details` input/output/total, `completion_start_time` để Langfuse tính TTFT.
  - Ví dụ trace `6ea28b95250f1c15c1d30fbbe094809e` (`req-a25aae7a`): generation 36 input / 180 output tokens, cost 0.002808 USD, TTFT 0.05 s (`evidence/07-trace-waterfall.png`).
- **Cách nối trace với log:** middleware sinh `correlation_id` (`x-request-id`) → được bind vào mọi log line và truyền vào `LabAgent.run`, nơi `propagate_attributes(metadata={"correlation_id": ...})` gắn nó vào mọi observation của trace. Trên Langfuse lọc Metadata `correlation_id = req-...` để mở đúng trace của một dòng log (`evidence/08-trace-metadata.png`). Trace còn có `user_id` (hash), `session_id`, tags `lab/<feature>/<model>`.
- **Prompt name:** `day13-chat` (text prompt, giữ 3 biến `{{feature}}`, `{{docs}}`, `{{message}}`).
- **Version/label baseline:** v1, labels `baseline` + `production`, template `Feature=…\nDocs=…\nQuestion=…`.
- **Version/label candidate:** v2, label `candidate`, thêm dòng "Answer in at most 3 short bullet points, using only the docs above." (thay đổi nhỏ về format/độ dài câu trả lời).
- **Trace ID của mỗi version:** cùng input "Explain why metrics traces and logs work together" (`evidence/10-prompt-rollback.txt`):

  | Bước | correlation_id | Trace ID | label → version | tokens_in |
  |---|---|---|---|---|
  | label baseline | `req-0001b001` | `db3aa40443dc125e339d8778000e26a6` | baseline → v1 | 32 |
  | label candidate | `req-0001c002` | `886c8be6274dca5c70c7193da247e3ea` | candidate → v2 | 49 |
  | production trước promote | `req-0001a003` | `dede46ae82f45aa456a6acad8ff30bf7` | production → v1 | 32 |
  | production sau promote v2 | `req-0001d004` | `5d089acb2aa4dc80111e00925ba0d861` | production → v2 | 49 |
  | production sau rollback | `req-0001e005` | `95c3af2ddd02b5a86e1ae9f08d94dc77` | production → v1 | 32 |

- **Cách promote và rollback `production`:** `python scripts/manage_prompt.py promote --version 2` gọi `update_prompt(new_labels=[..., "production"])` cho v2. Label là duy nhất giữa các version nên Langfuse tự gỡ `production` khỏi v1. Rollback bằng `promote --version 1`. App đọc label qua `LANGFUSE_PROMPT_LABEL` và cache prompt 60 s, nên restart API hoặc chờ hết TTL rồi request tiếp theo sẽ dùng version mới. Không cần deploy lại code. Bằng chứng: `status` trước/sau mỗi bước và trace production v1 → v2 → v1 ở bảng trên (`evidence/09-prompt-versions.png`, `evidence/10-prompt-rollback.png`, `evidence/10-prompt-rollback.txt`).

## 6. Dashboard, SLO và alerts

- **Dashboard và sáu panel:** `python scripts/dashboard.py` → <http://127.0.0.1:8050>. Script không cần thư viện mới, tính lại mọi số từ `data/logs.jsonl` mỗi lần tải trang. Tiêu đề, đơn vị, time range 60 phút, refresh 30 s và threshold đều đọc từ `config/dashboard.yaml`. Sáu panel:
  1. Latency: P50/P95/P99 và TTFT P95, threshold P95 ≤ 3000 ms, thêm đường SLO 2000 ms.
  2. Traffic: count và request/phút, threshold ≥ 1.
  3. Errors: error rate, `count_by(error_type)` và retrieval success (`tool_success`), threshold ≤ 2%.
  4. Cost: USD theo phút và tổng, threshold ≤ 2.5 USD.
  5. Tokens: tổng input/output, threshold ≤ 50000.
  6. Quality: mean `quality_score`, threshold ≥ 0.75.

  Mỗi panel có badge OK/BREACH so với threshold. `validate_dashboard.py` = 6/6 (`evidence/03-dashboard-validator.*`). Test: `tests/test_dashboard_runtime.py` (`evidence/11-dashboard-overview.png`).
- **SLO và lý do chọn:** `fast_successful_requests`: 99.5% request (mẫu số `request_received`) trả `response_sent` trong ≤ 2000 ms, cửa sổ 28 ngày (`config/slo.yaml`). Tôi hạ ngưỡng từ 3000 ms xuống 2000 ms dựa trên số đo:
  - Warm P50 ≈ 152 ms, P95 ≈ 153 ms.
  - Cold prompt fetch khi cache prompt hết hạn: 1.2–1.9 s.
  - Chạy thử `rag_slow` trên server tách riêng: 2653 ms, nên ngưỡng 3000 ms cũ không bắt được sự cố retrieval chậm.

  Target 99.5% vì dịch vụ phụ thuộc Langfuse Cloud và vector store bên ngoài.
- **Cách tính error budget:** budget = 100% − 99.5% = 0.5% số request, tức `allowed_bad = 0.005 × total`. Ví dụ 10,000 request / 28 ngày → 50 request được phép chậm hoặc lỗi (≈ 1.8/ngày). Burn rate = tỷ lệ request xấu / 0.5%. Error rate 2% (guardrail) = burn rate 4, hết budget sau 7 ngày. 7.2% = burn rate 14.4, tiêu 2% budget mỗi giờ nên cần page ngay. Chính sách khi dùng quá 50% hoặc hết budget: thay đổi prompt/model phải qua `candidate`, rồi rollback `production`.
- **Ba alert và runbook tương ứng:** `config/alert_rules.yaml` + `docs/alerts.md`. Cả ba đều symptom-based, gửi Slack `#day13-k4-l3a-alerts`, owner Đỗ Thanh Tùng (on-call):
  1. `HighLatencyP95` (P2, 5m): P95 latency > 2000 ms → [runbook](../docs/alerts.md#alert-1).
  2. `HighErrorRate` (P1, 5m): error rate > 2% hoặc retrieval success < 90% → [runbook](../docs/alerts.md#alert-2).
  3. `CostPerRequestSpike` (P3, 15m): avg cost > 0.004 USD/request, tức ≈ 2× baseline 0.0019. Chạy thử `cost_spike` cho 0.0058–0.0107 USD → [runbook](../docs/alerts.md#alert-3).

  Mỗi runbook có ảnh hưởng người dùng, 3 bước kiểm tra theo Metrics → Logs → Traces và mitigation.

## 7. Điều tra challenge

- **Challenge ID:** `day13-k4-l3a-monitoring-llmops-v1`, cohort K4, seed 1311, affected feature `monitoring`, `latency_threshold_ms` 2000. File lấy từ release "Challenge File" của repo đề bài `VinUni-AI20k/K4-L3A-Day13-Monitoring-LLMOps` (sha256 `b11e6286…86f6bf`), lưu tại `config/challenge.json`, không sửa và không commit (đã `.gitignore`).
- **Khoảng thời gian điều tra:** 2026-09-29 09:17:32Z → 09:17:48Z (16:17:32 → 16:17:48 giờ VN). Mốc: bật incident bằng `inject_incident.py` lúc 09:17:32Z, 5 request challenge từ 09:17:33Z đến 09:17:48Z, mitigation lúc 09:22:47Z (`evidence/12-incident-run.txt`).
- **Triệu chứng từ metrics:** dashboard zoom 10 phút (`evidence/12-incident-metric.png`): panel Latency chuyển **BREACH**.
  - P50 = 2653 ms, P95 = P99 = 3867 ms, vượt threshold P95 3000 ms và SLO 2000 ms. Baseline là P50 153 ms (`evidence/12b-incident-metric-60m.png`).
  - TTFT P95 vẫn 51 ms. Error rate 0%, retrieval success 100%, cost 0.0113 USD và quality 0.84 đều bình thường.

  Kết luận: triệu chứng là chậm, không phải lỗi hay tốn chi phí, và nằm trước bước sinh token.
- **Log line và correlation ID liên quan:** lọc `data/logs.jsonl` trong khoảng sự cố (`evidence/13-incident-log.png`, `evidence/13-incident-log.txt`): cả 5 `response_sent` của feature `monitoring` có `latency_ms` 2652–3867, `ttft_ms` 50. Chọn `req-54bee2d5`:
  `{"event": "response_sent", "correlation_id": "req-54bee2d5", "feature": "monitoring", "latency_ms": 2652, "ttft_ms": 50, "tool_name": "retrieval", "tool_success": true, "session_id": "k4-l3a-challenge-s02", "ts": "2026-09-29T09:17:39.923354Z", ...}`
- **Trace ID và span gây ảnh hưởng:** trace `2329bdf58878acca2642e46caf0b3455` có metadata `correlation_id = req-54bee2d5` (`evidence/14b-incident-trace-metadata.png`). Timeline (`evidence/14-incident-trace.png`):
  - `lab-agent-run` 2.65 s, trong đó **`retrieve` 2.50 s (≈ 94%)**.
  - `resolve-prompt` 1 ms, `llm-generate` 151 ms (TTFT 0.05 s).
  - Trace baseline cùng cấu trúc (`6ea28b95250f1c15c1d30fbbe094809e`) có `retrieve` ≈ 0 ms.
  - Cả 5 trace challenge đều có `retrieve` ≈ 2.50 s. Riêng `req-2597662b` (trace `e3820ea502e49a6e69a83e42f1e089f3`, 3867 ms) cộng thêm 1.2 s ở `resolve-prompt`, do cold prompt fetch khi request đầu tiên sau khi API reload phải lấy prompt từ Langfuse. Đây là yếu tố phụ, không phải root cause.
- **Root cause:** incident `rag_slow` làm bước retrieval (vector store, `app/mock_rag.py`) chậm thêm ≈ 2.5 s mỗi request. Retrieval chạy tuần tự trước khi gọi LLM nên toàn bộ độ trễ cộng thẳng vào latency, trong khi LLM và prompt không đổi. Metric (P50/P95 tăng, TTFT và error bình thường), log (`latency_ms` 2652 nhưng `ttft_ms` 50) và trace (`retrieve` 2.50 s / 2.65 s) cùng chỉ về một span. Thêm nữa, endpoint `async def /chat` gọi agent đồng bộ nên các request đồng thời bị xếp hàng: client của request cuối phải chờ 14.8 s dù server chỉ đo 2.65 s.
- **Fix action:** theo runbook Alert 1, gỡ nguồn chậm bằng `python scripts/inject_incident.py --disable` (tương đương khôi phục vector store / chuyển sang index dự phòng). Kiểm chứng bằng cách chạy lại đúng 5 query challenge: `latency_ms` giảm từ [3867, 2652, 2654, 2653, 2652] xuống [1333, 151, 152, 152, 152]. Request 1333 ms là cold prompt fetch, `retrieve` về ≈ 0 ms (`evidence/12-incident-run.txt`).
- **Preventive measure:**
  1. Đặt timeout ~500 ms cho retrieval kèm fallback (cache kết quả gần nhất hoặc trả lời "không có tài liệu") để vector store chậm không kéo cả request quá SLO.
  2. Chạy agent đồng bộ bằng `run_in_threadpool` (hoặc đổi endpoint thành `def`) để một request chậm không chặn event loop và các request khác.
  3. Thêm alert riêng cho span `retrieve` (P95 duration > 500 ms trong 5 phút) bên cạnh `HighLatencyP95`, vì alert tổng cần 5 phút mới bắn còn sự cố challenge chỉ kéo dài 16 s.
  4. Warm-up prompt khi API khởi động và tăng `cache_ttl_seconds` để loại cold prompt fetch 1.2 s khỏi tail latency.

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
