# BÁO CÁO BÀI TẬP — Data Siege

**Học viên:** Trần Mạnh Chánh Quân  
**Mã học viên:** 2A202600786  
**Ngày:** 2026-07-03  
**Môn:** AI2k — Day 27, Track 2  

---

## 1. GIỚI THIỆU

Data Siege là bài tập mô phỏng việc bảo vệ một data pipeline trước các lỗi dữ liệu (data faults). Hệ thống sẽ gửi một stream các sự kiện pipeline theo thứ tự, và nhiệm vụ là với mỗi sự kiện, đưa ra quyết định **alert** (cảnh báo có lỗi) hoặc **stay quiet** (bỏ qua). Bài tập gồm 3 phase: Practice, Public, và Private — trong đó Private là phase tính điểm chính thức.

## 2. CẤU TRÚC HỆ THỐNG

```
data/
  baselines.json          — Các hằng số baseline (mean ± 3σ từ clean stream)
docs/
  TOOLKIT_API.md           — API reference cho ctx.tools
  FAULT_PILLARS.md         — Mô tả 4 pillar lỗi cần phát hiện
  SUBMIT.md                — Hướng dẫn nộp bài
harness/
  run.py                   — Entrypoint chạy phase
  selfcheck.py             — Kiểm tra cấu trúc defense.py
  scoring.py               — Tính điểm
  isolation.py             — Cô lập defense.py trong subprocess
  toolkit/metering.py      — Server-side toolkit + cost ledger
  child_env/api.py         — Interface cho defense.py (SiegeContext, ToolkitProxy, Verdict)
solution/
  defense.py               — **NƠI CẦN IMPLEMENT** — detection logic
  reflection.md            — Bài reflection ≤1 trang
submission/
  manifest.json            — Manifest nộp bài
```

## 3. BỐN PILLAR LỖI (FAULT PILLARS)

| Pillar | Event Type | Tool | Mô tả |
|--------|-----------|------|-------|
| **checks** | `data_batch` | `batch_profile()` | Lỗi về freshness, volume, null-rate, phân phối của batch dữ liệu |
| **contracts** | `contract_checkpoint` | `contract_diff()` | Producer vi phạm ODCS contract: schema, type, SLA |
| **lineage** | `lineage_run` | `lineage_graph_slice()` | Lineage graph bất thường: thiếu upstream, orphaned output, runtime bất thường |
| **ai_infra** | `feature_materialization`, `embedding_batch` | `feature_drift()`, `embedding_drift()` | Training-serving skew, embedding/RAG drift hoặc staleness |

## 4. CÔNG THỨC ĐIỂM

$$score = 100 \times (0.5 \cdot TPR - 0.3 \cdot FPR - 0.2 \cdot \min(cost\_overage, 1))$$

- **TPR** (True Positive Rate): Tỉ lệ bắt được lỗi thật
- **FPR** (False Positive Rate): Tỉ lệ báo động giả
- **cost_overage**: Mức vượt ngân sách (budget = 220 credits)

## 5. CHIẾN LƯỢC PHÁT HIỆN (Final v3)

### 5.1. Tổng quan kiến trúc

Defense module gồm 3 tầng: **Helpers** (hàm tiện ích), **Budget Manager** (quản lý ngân sách), và **5 Handlers** (mỗi handler cho một event type).

### 5.2. Helpers — Các hàm nền tảng

| Hàm | Chức năng | Chi tiết |
|-----|-----------|----------|
| `_is_error(result)` | Kiểm tra tool lỗi | Trả về `True` nếu response có key `"error"` → fallback an toàn (alert=False) |
| `_exceeds(value, threshold)` | Kiểm tra vượt ngưỡng trên | `value > threshold × 1.1` (10% tightening trên baseline 3σ → ~3.3σ) |
| `_below(value, threshold)` | Kiểm tra dưới ngưỡng dưới | `value < threshold × 0.9` (10% tightening) |
| `_get_dist_params(min, max)` | Reverse-engineer μ, σ | Từ baseline bounds (μ±3σ): μ=(max+min)/2, σ=(max-min)/6 |

**Lý do margin 10%:** Baseline đã là μ±3σ (99.7% confidence). Thực nghiệm cho thấy có ~1 clean event nằm ở ~3.1σ trên Public → gây FP nếu dùng exact baseline. Margin 10% (→~3.3σ) loại bỏ FP này.

### 5.3. Budget Manager — Dynamic Sampling

```python
def _budget_safe(ctx, cost):
    if cost ≤ 1.5: return remaining ≥ cost       # Luôn cho phép tool rẻ
    if remaining > 50: return True                # Budget dồi dào → luôn gọi
    probability = max(0.15, remaining / 50)       # Budget < 50 → xác suất giảm dần
    return random.random() < probability
```

- Tool ≤1.5 credits (`batch_profile`, `lineage_graph_slice`, `contract_diff`): luôn được gọi
- Tool 2.0 credits (`feature_drift`, `embedding_drift`): probabilistic throttle khi budget < 50
- Đảm bảo không bao giờ cạn budget giữa chừng

### 5.4. Handler: `data_batch` (pillar: checks) — Cost: 1.0/event

**Dual Hard/Soft Threshold:**

| Metric | Hard (alert ngay) | Soft (cần ≥2) |
|--------|-------------------|---------------|
| row_count | < min×0.9 hoặc > max×1.1 | gần baseline (±5%) |
| null_rate | > max×1.1 | > max×0.9 |
| mean_amount | < min×0.9 hoặc > max×1.1 | — |
| staleness_min | > max×1.1 | > max×0.95 |

**Rolling Z-score với Regularization:**
- Lưu history 50 mẫu `(mean_amount, std_amount)` gần nhất vào `ctx.state`
- Cần ≥15 mẫu để thống kê đủ tin cậy
- Tính Z-score: `z = |ma - μ_sample| / safe_sigma`
- **Regularization:** `safe_sigma = max(sample_sigma, global_sigma × 0.3, 1e-6)` — chặn FPR khi local variance quá nhỏ
- Alert nếu Z > 3.5

**Variance Collapse Detection:**
- Phát hiện `std_amount` giảm đột ngột < 25% trung bình lịch sử

**Quyết định:** Alert nếu ≥1 Hard HOẶC ≥2 Soft

### 5.5. Handler: `contract_checkpoint` (pillar: contracts) — Cost: 1.5/event

| Kiểm tra | Cách thức |
|----------|-----------|
| freshness_delay_min | `_exceeds()` vs `baseline.freshness_delay_max_min` |
| violations[] | Nếu list không rỗng → alert ngay (schema_hash_mismatch, type_violation = certain fault) |

### 5.6. Handler: `lineage_run` (pillar: lineage) — Cost: 1.0/event

| Kiểm tra | Cách thức |
|----------|-----------|
| duration_ms | `_exceeds()` vs `baseline.lineage_duration_ms_max` |
| missing_upstream | **MAX-based**: lưu `max_upstream` vào state. Nếu `up_len < max_up` → alert. Cold-start proof vì max chỉ tăng, không giảm |
| orphan_output | `downstream_count == 0` → alert |

**Tại sao MAX thay vì MODE:** Mode có thể bị "nhiễm" nếu fault xuất hiện sớm. MAX luôn phản ánh topology hoàn chỉnh nhất từng thấy.

### 5.7. Handler: `feature_materialization` (pillar: ai_infra) — Cost: 2.0/event

| Kiểm tra | Cách thức |
|----------|-----------|
| mean_shift_sigma | `_exceeds()` vs `baseline.feature_mean_shift_sigma_max` |
| Z-skew thủ công | `|serve_mean - train_mean| / train_std > 3.0` — redundancy check |
| Confidence | Tỉ lệ với mức vượt ngưỡng: `0.7 + 0.1 × over_ratio` |

### 5.8. Handler: `embedding_batch` (pillar: ai_infra) — Cost: 2.0/event

| Kiểm tra | Cách thức |
|----------|-----------|
| centroid_shift | `_exceeds()` vs `baseline.embedding_centroid_shift_max` |
| avg_doc_age_days | `_exceeds()` vs `baseline.corpus_avg_doc_age_days_max` |
| Decision | Alert nếu ít nhất 1 trong 2 vượt ngưỡng |

## 6. KẾT QUẢ

### 6.1. Practice Phase

| Chỉ số | Kết quả |
|--------|---------|
| **Score** | **50.00 / 50** |
| TPR (True Positive Rate) | 1.0000 (33/33 faults caught) |
| FPR (False Positive Rate) | 0.0000 (0/87 false alarms) |
| Cost | 180.00 / 220.00 (dư 40 credits) |
| Cost Overage | 0.00 |

| Pillar | Band | Ghi chú |
|--------|------|---------|
| checks | 🟢 **high** | Bắt được tất cả: freshness_lag, distribution_shift, volume_spike, null_spike |
| contracts | 🟢 **high** | Bắt được tất cả: type_violation, schema_break |
| lineage | 🟢 **high** | Bắt được tất cả: runtime_anomaly, missing_upstream, orphan_output |
| ai_infra | 🟢 **high** | Bắt được tất cả: feature_skew (cả obvious lẫn subtle), embedding_drift, corpus_staleness |

### 6.2. Public Phase

| Chỉ số | Kết quả |
|--------|---------|
| **Score** | **44.62 / 50** |
| TPR | 0.8974 (35/39 faults caught) |
| FPR | 0.0083 (1/121 false alarms) |
| Cost | 218.00 / 220.00 |
| Cost Overage | 0.00 |

| Pillar | Band |
|--------|------|
| checks | 🟢 high |
| contracts | 🟢 high |
| lineage | 🟢 high |
| ai_infra | 🟢 high |

### 6.3. Lịch sử tinh chỉnh (7 vòng)

| Vòng | TPR | FPR | Cost | Score | Thay đổi |
|------|-----|-----|------|-------|----------|
| V1 | 0.8182 | 0.0 | 180 | 40.91 | Baseline: signal weight conservative → bỏ borderline |
| V2 | 0.9394 | 0.0 | 180 | 46.97 | Lineage: thêm mode tracking cho upstream |
| V3 | 1.0000 | 0.0 | 180 | **50.00** | Lineage: median→mode (robust với fault contamination) |
| V4 | 0.9231 | 0.0165 | 240 | 43.84 | Public baseline: cost vượt 20, 2 FP |
| V5 | 0.8974 | 0.0165 | 218 | 44.38 | Budget throttle (20), cost về 218 |
| V6 | 0.8974 | 0.0083 | 218 | 44.62 | Tighten 10% → giảm 1 FP |
| **V7** | **0.8974** | **0.0083** | **218** | **44.62** | +Z-score regularization, MAX lineage, dynamic sampling |

### 6.4. Đóng góp từ AI (Gemini)

| Model | Đề xuất chính | Áp dụng |
|-------|--------------|---------|
| Gemini 3.5 Flash | Dual Hard/Soft threshold, Rolling Z-score, Variance collapse, Z-skew, Cold-start fix | ✅ Tất cả |
| Gemini 3.1 Pro | Global-sigma regularization (30% floor), MAX upstream thay MODE, Dynamic sampling budget, Bỏ margin 1.1 | ✅ 3/4 (giữ margin 1.1 vì thực nghiệm chứng minh cần thiết) |

### 6.5. Các phase còn lại

| Phase | Mô tả | Kết quả |
|-------|-------|---------|
| Private | Đánh giá chính thức | ⬜ Chờ key |

## 7. KẾT LUẬN

### Tổng kết

| Phase | Score | TPR | FPR | Cost | All Pillars |
|-------|-------|-----|-----|------|-------------|
| Practice | **50.00** | 100% | 0% | 180/220 | 🟢🟢🟢🟢 |
| Public | **44.62** | 89.74% | 0.83% | 218/220 | 🟢🟢🟢🟢 |
| Private | ⬜ | — | — | — | Chờ key |

### Kiến trúc defense (v3 final)

```
helpers: _is_error | _exceeds(×1.1) | _below(×0.9) | _get_dist_params
budget:  _budget_safe (dynamic sampling: probabilistic < 50 credits)
state:   batch_stats[] | lineage_max_upstream (cross-event tracking)
──────────────────────────────────────────────────────────
data_batch           → Dual Hard/Soft + Rolling Z-score(reg) + Variance collapse
contract_checkpoint  → Freshness delay + Violations list
lineage_run          → Duration + MAX upstream + Orphan downstream
feature_materialization → mean_shift_sigma + Manual Z-skew
embedding_batch      → centroid_shift + avg_doc_age
```

### Bài học chính

1. **Baseline = 3σ đã đủ cho obvious faults**, nhưng cần margin 10% để tránh FP từ normal variance ở ~3.1σ
2. **Mode dễ bị fault contamination** — MAX an toàn hơn cho topology detection
3. **Rolling Z-score cần regularization** — nếu không, local variance nhỏ gây nổ Z-score → FP
4. **Dynamic sampling > Fixed throttle** — giữ được coverage khi budget dồi dào, tiết kiệm khi cạn
5. **Dual threshold (Hard/Soft)** cân bằng tốt TPR/FPR: 1 hard = alert, cần ≥2 soft mới alert

### Trạng thái nộp bài

| Hạng mục | File | Trạng thái |
|----------|------|-----------|
| Detection logic | `solution/defense.py` | ✅ Hoàn thiện |
| Reflection | `solution/reflection.md` | ✅ Đã viết |
| Manifest | `submission/manifest.json` | ✅ Đã điền thông tin |
| Private report | `solution/private_report.json` | ⬜ Chờ private key |
| Practice report | `solution/practice_report.json` | ✅ Score 50/50 |
| Public report | `solution/public_report.json` | ✅ Score 44.38 |

**Học viên:** Trần Mạnh Chánh Quân — **MSSV:** 2A202600786
