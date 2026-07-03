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

## 5. CHIẾN LƯỢC PHÁT HIỆN

### 5.1. Phương pháp chung
- So sánh kết quả tool calls với `ctx.baseline` (các hằng số calibrated từ clean stream)
- Kết hợp nhiều tín hiệu cho các lỗi subtle (không chỉ dùng threshold đơn lẻ)
- Sử dụng `ctx.state` để cache và theo dõi trạng thái qua các events
- Luôn kiểm tra key `"error"` trong response từ tool calls

### 5.2. Quản lý ngân sách
- Budget: 220 credits
- Ưu tiên tool rẻ (`batch_profile`: 1.0, `lineage_graph_slice`: 1.0)
- Cache kết quả vào `ctx.state` để tránh gọi lại
- Gọi `spend_so_far()` / `budget_remaining()` (free) để theo dõi

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
| **Score** | **44.38 / 50** |
| TPR | 0.8974 (35/39 faults caught) |
| FPR | 0.0165 (2/121 false alarms) |
| Cost | 218.00 / 220.00 |
| Cost Overage | 0.00 |

| Pillar | Band |
|--------|------|
| checks | 🟢 high |
| contracts | 🟢 high |
| lineage | 🟢 high |
| ai_infra | 🟢 high |

### 6.3. Chi tiết quá trình tinh chỉnh

| Vòng | TPR | FPR | Score | Vấn đề & Sửa |
|------|-----|-----|-------|-------------|
| V1 | 0.8182 | 0.0 | 40.91 | data_batch: signal weight quá conservative → bỏ borderline logic |
| V2 | 0.9394 | 0.0 | 46.97 | lineage: chỉ bắt empty upstream → thêm mode tracking |
| V3 | 1.0000 | 0.0 | **50.00** | lineage: median → mode (robust với fault contamination) |
| V4 | 0.9231 | 0.0165 | 43.84 | Public: thêm budget throttle (threshold=20) để giảm cost 240→218 |
| V5 | 0.8974 | 0.0165 | **44.38** | Public final: cost trong budget, tất cả pillar high |

### 6.4. Các phase còn lại

| Phase | Mô tả | Kết quả |
|-------|-------|---------|
| Private | Đánh giá chính thức | ⬜ Chờ key |

## 7. KẾT LUẬN

### Tổng kết kỹ thuật

- **Practice**: 50/50 — TPR 100%, FPR 0%, tất cả pillar "high"
- **Public**: 44.38/50 — TPR 89.74%, FPR 1.65%, cost trong budget (218/220)
- **Chiến lược chính**: Baseline thresholds (mean ± 3σ) + Mode tracking cho structural anomalies + Budget throttle cho tool đắt
- **Bài học**: Mode robust hơn mean/median khi dữ liệu bị fault contamination; baseline đơn lẻ đã đủ ý nghĩa thống kê, không cần conservative multi-signal requirement

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
