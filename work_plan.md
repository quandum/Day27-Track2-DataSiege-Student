# KẾ HOẠCH THỰC HIỆN — Data Siege

**Học viên:** Trần Mạnh Chánh Quân  
**Mã học viên:** 2A202600786  
**Ngày lập:** 2026-07-03  

---

## TỔNG QUAN DỰ ÁN

Data Siege là bài tập bảo vệ data pipeline. Một stream các sự kiện pipeline (data_batch, contract_checkpoint, lineage_run, feature_materialization, embedding_batch) sẽ lần lượt được gửi đến `solution/defense.py`. Nhiệm vụ: với mỗi sự kiện, quyết định **alert** (cảnh báo lỗi) hoặc **stay quiet** (bỏ qua). Điểm số dựa trên công thức:

$$score = 100 \times (0.5 \cdot TPR - 0.3 \cdot FPR - 0.2 \cdot \min(cost\_overage, 1))$$

Có 3 phase: **Practice** (luyện tập, có answer key), **Public** (bảng xếp hạng chung), **Private** (đánh giá chính thức).

---

## CÁC BƯỚC THỰC HIỆN

### GIAI ĐOẠN 1: THIẾT LẬP MÔI TRƯỜNG

| Bước | Công việc | Mô tả chi tiết | Trạng thái |
|------|-----------|----------------|------------|
| 1.1 | Cài đặt môi trường Python | `pip install --break-system-packages -r requirements.txt` | ✅ Đã xong |
| 1.2 | Chạy selfcheck | `python3 harness/selfcheck.py` để xác nhận cấu trúc `defense.py` hợp lệ | ✅ Đã xong |
| 1.3 | Đọc & hiểu tài liệu | `docs/TOOLKIT_API.md`, `docs/FAULT_PILLARS.md`, `docs/SUBMIT.md`, `RULES.md` | ✅ Đã xong |
| 1.4 | Điền thông tin cá nhân | Cập nhật `submission/manifest.json` với tên & mã học viên | ✅ Đã xong |

---

### GIAI ĐOẠN 2: PHÁT TRIỂN DEFENSE.PY — HANDLER `data_batch`

**Pillar:** `checks`  
**Tool:** `ctx.tools.batch_profile(batch_id)` → cost 1.0  
**Baseline đối chiếu:**
- `row_count_min` / `row_count_max`
- `null_rate_max`
- `mean_amount_min` / `mean_amount_max`
- `staleness_min_max`

| Bước | Công việc | Mô tả chi tiết | Trạng thái |
|------|-----------|----------------|------------|
| 2.1 | Gọi `batch_profile()` | Lấy `{row_count, null_rate:{customer_id}, mean_amount, std_amount, staleness_min}` | ✅ |
| 2.2 | Kiểm tra row_count | So sánh với `baseline.row_count_min` / `baseline.row_count_max`; alert nếu ngoài khoảng | ✅ |
| 2.3 | Kiểm tra null_rate | So sánh `null_rate.customer_id` với `baseline.null_rate_max`; alert nếu vượt ngưỡng | ✅ |
| 2.4 | Kiểm tra mean_amount | So sánh với `baseline.mean_amount_min` / `baseline.mean_amount_max` | ✅ |
| 2.5 | Kiểm tra staleness | So sánh `staleness_min` với `baseline.staleness_min_max` | ✅ |
| 2.6 | Kết hợp tín hiệu (statistical judgment) | Alert nếu bất kỳ signal nào vượt baseline (mean ± 3σ) — mỗi signal riêng lẻ đã đủ ý nghĩa thống kê | ✅ |
| 2.7 | Tối ưu cost | Gọi tool 1 lần/event; cost 1.0 | ✅ |

---

### GIAI ĐOẠN 3: PHÁT TRIỂN DEFENSE.PY — HANDLER `contract_checkpoint`

**Pillar:** `contracts`  
**Tool:** `ctx.tools.contract_diff(contract_id, checkpoint_batch_id)` → cost 1.5  
**Baseline:** `freshness_delay_max_min`

| Bước | Công việc | Mô tả chi tiết | Trạng thái |
|------|-----------|----------------|------------|
| 3.1 | Gọi `contract_diff()` | Lấy `{freshness_delay_min, violations: [...]}` | ✅ |
| 3.2 | Kiểm tra freshness_delay | So sánh với `baseline.freshness_delay_max_min` | ✅ |
| 3.3 | Kiểm tra violations | Nếu danh sách violations KHÔNG rỗng → alert (schema_hash_mismatch, type_violation) | ✅ |
| 3.4 | Xử lý edge cases | Kiểm tra key `"error"` trong response trước khi xử lý | ✅ |

---

### GIAI ĐOẠN 4: PHÁT TRIỂN DEFENSE.PY — HANDLER `lineage_run`

**Pillar:** `lineage`  
**Tool:** `ctx.tools.lineage_graph_slice(run_id, depth=1)` → cost 1.0 × depth  
**Baseline:** `lineage_duration_ms_max`

| Bước | Công việc | Mô tả chi tiết | Trạng thái |
|------|-----------|----------------|------------|
| 4.1 | Gọi `lineage_graph_slice()` | Lấy `{duration_ms, actual_upstream, actual_downstream_count}` | ✅ |
| 4.2 | Kiểm tra duration_ms | So sánh với `baseline.lineage_duration_ms_max` | ✅ |
| 4.3 | Kiểm tra upstream/downstream | Dùng mode tracking để phát hiện missing_upstream; downstream_count=0 → orphan_output | ✅ |
| 4.4 | Lưu lịch sử lineage vào state | Dùng `ctx.state` để theo dõi mode của upstream lengths qua các lần gọi | ✅ |

---

### GIAI ĐOẠN 5: PHÁT TRIỂN DEFENSE.PY — HANDLER `feature_materialization`

**Pillar:** `ai_infra`  
**Tool:** `ctx.tools.feature_drift(feature_view, ref)` → cost 2.0  
**Baseline:** `feature_mean_shift_sigma_max`

| Bước | Công việc | Mô tả chi tiết | Trạng thái |
|------|-----------|----------------|------------|
| 5.1 | Gọi `feature_drift()` | Lấy `{serve_mean, train_mean, train_std, mean_shift_sigma}` | ✅ |
| 5.2 | Kiểm tra mean_shift_sigma | So sánh với `baseline.feature_mean_shift_sigma_max` | ✅ |
| 5.3 | Phân tích phân phối | Dùng serve_mean, train_mean, train_std để tính thêm Z-score / khoảng tin cậy | ✅ |

---

### GIAI ĐOẠN 6: PHÁT TRIỂN DEFENSE.PY — HANDLER `embedding_batch`

**Pillar:** `ai_infra`  
**Tool:** `ctx.tools.embedding_drift(corpus, ref)` → cost 2.0  
**Baseline:** `embedding_centroid_shift_max`, `corpus_avg_doc_age_days_max`

| Bước | Công việc | Mô tả chi tiết | Trạng thái |
|------|-----------|----------------|------------|
| 6.1 | Gọi `embedding_drift()` | Lấy `{centroid_shift, avg_doc_age_days}` | ✅ |
| 6.2 | Kiểm tra centroid_shift | So sánh với `baseline.embedding_centroid_shift_max` | ✅ |
| 6.3 | Kiểm tra avg_doc_age_days | So sánh với `baseline.corpus_avg_doc_age_days_max` | ✅ |
| 6.4 | Kết hợp cả 2 tín hiệu | Alert nếu một trong hai vượt ngưỡng, tăng confidence nếu cả hai cùng vượt | ✅ |

---

### GIAI ĐOẠN 7: CHIẾN LƯỢC TOÀN CỤC

| Bước | Công việc | Mô tả chi tiết | Trạng thái |
|------|-----------|----------------|------------|
| 7.1 | Quản lý ngân sách (budget = 220) | Cost hiện tại: 180/220, dư 40 — an toàn | ✅ |
| 7.2 | Cache/memoization | Lưu upstream/downstream mode vào `ctx.state` để so sánh | ✅ |
| 7.3 | Xử lý lỗi tool call | Luôn kiểm tra key `"error"` trong response; fallback an toàn (alert=False) | ✅ |
| 7.4 | Confidence score | Điều chỉnh dựa trên số lượng signals và mức vượt ngưỡng | ✅ |
| 7.5 | Reason string | Ghi rõ lý do alert (vd: "row_count 800 > max 561.3") | ✅ |
| 7.6 | Anti-overfit | Dùng baseline + mode tracking; không hardcode giá trị cụ thể | ✅ |

---

### GIAI ĐOẠN 8: KIỂM THỬ & TINH CHỈNH

| Bước | Công việc | Mô tả chi tiết | Trạng thái |
|------|-----------|----------------|------------|
| 8.1 | Chạy selfcheck | `python3 harness/selfcheck.py` — đảm bảo code clean | ✅ |
| 8.2 | Chạy Practice phase | `python3 harness/run.py --phase practice --defense solution/defense.py --out solution/practice_report.json` | ✅ Score: 50/50 |
| 8.3 | So sánh với answer key | Đối chiếu `solution/practice_report.json` với `phases/practice_answer_key.json` | ✅ TPR=1.0, FPR=0.0 |
| 8.4 | Phân tích lỗi | Tất cả 33/33 faults đã bắt được, 0 false positives | ✅ |
| 8.5 | Lặp lại tinh chỉnh | Sửa defense.py → chạy lại practice → phân tích → đạt 50/50 | ✅ |
| 8.6 | Chạy Public phase | `python3 harness/run.py --phase public --defense solution/defense.py --out solution/public_report.json` | ✅ Score: 44.38 |
| 8.7 | Phân tích per-pillar band | Tất cả pillar đều "high" | ✅ |

---

### GIAI ĐOẠN 9: HOÀN THIỆN & NỘP BÀI

| Bước | Công việc | Mô tả chi tiết | Trạng thái |
|------|-----------|----------------|------------|
| 9.1 | Viết `solution/reflection.md` | ≤1 trang: fault type nào khó nhất, tradeoff cost/coverage sẽ thay đổi gì | ⬜ |
| 9.2 | Cập nhật `submission/manifest.json` | Điền `team_or_student`: "Trần Mạnh Chánh Quân - 2A202600786" | ⬜ |
| 9.3 | Chạy Private phase | `python3 harness/run.py --phase private --defense solution/defense.py --out solution/private_report.json` (khi có key) | ⬜ |
| 9.4 | Selfcheck lần cuối | `python3 harness/selfcheck.py` | ⬜ |
| 9.5 | Git commit & push | `git add solution/ submission/ && git commit -m "submission" && git push` | ⬜ |
| 9.6 | Kiểm tra repo | Xác nhận `defense.py`, `reflection.md`, `private_report.json` đã được push | ⬜ |

---

## PHÂN BỔ NGÂN SÁCH DỰ KIẾN (Budget = 220)

| Event type | Tool cost / event | Dự kiến số events | Tổng cost dự kiến |
|------------|-------------------|-------------------|-------------------|
| data_batch | 1.0 | ~30-40 | ~30-40 |
| contract_checkpoint | 1.5 | ~20-30 | ~30-45 |
| lineage_run | 1.0 | ~25-35 | ~25-35 |
| feature_materialization | 2.0 | ~15-25 | ~30-50 |
| embedding_batch | 2.0 | ~15-25 | ~30-50 |
| **Tổng dự kiến** | | | **~145-220** |

⚠️ Cần chiến lược tiết kiệm: cache kết quả, skip tool call nếu có dấu hiệu rõ ràng từ payload, ưu tiên tool rẻ.

---

## GHI CHÚ QUAN TRỌNG

- **KHÔNG** đọc trực tiếp file `phases/*.key` hay `phases/*_schedule.json.enc`
- **KHÔNG** hardcode answer key (vd: `if event_id == "b-0042": alert=True`)
- **KHÔNG** gọi RPC method ngoài danh sách trong `docs/TOOLKIT_API.md`
- **CHỈ** sửa file trong `solution/` và `submission/`
- Private phase có tỉ lệ lỗi subtle cao hơn → logic detection phải tổng quát, không overfit practice/public
