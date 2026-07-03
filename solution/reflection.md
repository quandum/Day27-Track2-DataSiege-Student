# Reflection — Trần Mạnh Chánh Quân (2A202600786)

## Hardest fault types to catch

**1. `missing_upstream` (lineage)** — Fault khó nhất, cần 3 vòng tinh chỉnh.
Vấn đề: upstream list không rỗng mà thiếu 1 phần tử (2→1). Mean bị fault
contamination kéo xuống, median không phát hiện được khác biệt 1 vs 2. Mode
bắt được nhưng cold-start (fault xuất hiện sớm) làm mode sai. Giải pháp cuối:
**MAX** — topology hoàn chỉnh nhất từng thấy, chỉ tăng không giảm → cold-start
proof. Bài học: với dữ liệu streaming có fault, max/min an toàn hơn mean/mode.

**2. `distribution_shift` & `freshness_lag` (checks)** — Chỉ vi phạm 1 tín hiệu.
Thiết kế ban đầu yêu cầu ≥2 signals → bỏ sót. Nhưng bỏ requirement này gây FP
trên Public (1 clean event ở ~3.1σ). Giải pháp: **dual Hard/Soft threshold** —
Hard = 3.3σ (alert ngay), Soft = 3σ (cần ≥2). Cân bằng được TPR và FPR.

**3. FP từ Rolling Z-score** — Local variance quá nhỏ gây Z-score nổ.
**Regularization**: floor safe_sigma = max(sample_sigma, global_sigma×0.3).

## Cost/coverage tradeoff

| Chiến lược | Hiệu quả |
|-----------|----------|
| Margin 10% trên baseline | Giảm FPR 2→1, giữ nguyên TPR → +0.24 điểm |
| Dynamic sampling (thay fixed throttle) | Cost 218→216, giữ coverage khi budget dồi dào |
| MAX upstream (thay mode) | Cold-start proof, không cần ≥3 mẫu warm-up |
| Z-score regularization (30% floor) | Ngăn FP từ tiny local variance |

## Điều sẽ thay đổi nếu có thêm một lượt

1. **Thêm payload pre-screening** — Một số event có thể skip tool call nếu
   payload chứa metadata gợi ý batch sạch. Hiện tại gọi tool 100% events.
2. **Adaptive margin** — Thay vì margin=1.1 cố định, điều chỉnh dynamic dựa
   trên số lượng event đã thấy: margin cao lúc đầu (an toàn), giảm dần khi có
   nhiều history (bắt subtle faults tốt hơn).
3. **Cross-pillar correlation** — Nếu data_batch và contract_checkpoint cùng
   ref bị lỗi → confidence cao hơn. Hiện tại mỗi handler hoạt động độc lập.
4. **Two-pass lineage** — depth=1 trước (cost 1.0), nếu nghi ngờ mới depth=2
   (thêm 1.0) để có thêm context về topology.

## Kết luận

Defense v3 đạt 50/50 Practice, 44.62/50 Public — điểm tối đa khả thi với
current tool outputs. 4 fault còn lại trên Public nằm ngoài tầm phát hiện
của mọi tổ hợp threshold/statistical approach hiện có. Các cải tiến từ
Gemini (dual threshold, Z-score reg, MAX lineage, dynamic sampling) đã được
tích hợp và kiểm chứng thực nghiệm. Sẵn sàng cho Private phase.

