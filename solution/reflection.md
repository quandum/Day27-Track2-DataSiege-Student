# Reflection — Trần Mạnh Chánh Quân (2A202600786)

## Hardest fault types to catch

**1. `missing_upstream` (lineage pillar)** — Đây là fault khó nhất, cần 3 vòng
tinh chỉnh mới bắt được. Vấn đề: upstream list không rỗng mà chỉ thiếu một phần
tử (2 → 1 entries). Cách tiếp cận ban đầu dùng running average bị "nhiễm" bởi
chính các fault trước đó — giá trị trung bình bị kéo xuống khiến các fault sau
trông "bình thường". Chuyển sang median cũng không giải quyết được vì median
của [2,2,2] = 2, không phát hiện được sự khác biệt với 1. Giải pháp cuối cùng:
dùng **mode** (giá trị xuất hiện nhiều nhất) của upstream lengths — mode luôn
là 2 (normal) nên bất kỳ độ dài nào < mode đều bị flag. Đây là bài học về
robustness của thống kê: mean/median dễ bị fault contamination, mode thì không.

**2. `distribution_shift` & `freshness_lag` (checks pillar)** — Các fault này
chỉ vi phạm MỘT tín hiệu đơn lẻ (mean_amount hoặc staleness). Thiết kế ban đầu
yêu cầu ≥2 tín hiệu hoặc tín hiệu "mạnh" mới alert → bỏ sót. Sửa: baseline đã
là mean ± 3σ, nên chỉ cần một tín hiệu vượt ngưỡng cũng đủ ý nghĩa thống kê để
alert. Không cần conservative threshold.

**3. `feature_skew` (subtle tier)** — Các fault subtle có mean_shift_sigma ≈ 2-3,
chỉ gấp ~5-7 lần baseline (0.41), trong khi obvious lên tới 15-19. Tuy nhiên
vẫn vượt baseline rõ ràng nên threshold đơn giản vẫn hoạt động tốt.

## Cost/coverage tradeoff — điều gì sẽ thay đổi nếu có thêm một lượt?

**Điểm mạnh hiện tại:** FPR = 0% trên Practice, cost trong budget trên Public.
Mode tracking cho lineage hoạt động robust.

**Điều sẽ thay đổi:**

1. **Adaptive budget allocation** — Thay vì throttle cứng ở threshold 20 cho
   tool 2.0-credit, sẽ phân bổ budget động dựa trên tỉ lệ fault từng pillar
   đã thấy. Nếu ai_infra faults hiếm hơn checks, ưu tiên budget cho checks.

2. **Payload pre-screening** — Một số event có thể được "screening" nhanh qua
   payload fields trước khi gọi tool. Ví dụ: nếu payload đã chứa metadata gợi
   ý batch size hoặc timestamp, có thể skip tool call nếu mọi thứ có vẻ bình
   thường. Điều này cần thêm research về cấu trúc payload.

3. **Two-pass detection cho lineage** — Pass 1: gọi `lineage_graph_slice(depth=1)`
   (cost 1.0). Nếu duration và upstream/downstream bình thường, dừng. Nếu
   nghi ngờ, pass 2: gọi với `depth=2` (thêm 1.0) để có thêm context. Hiện
   tại luôn dùng depth=1.

4. **Giảm FPR trên Public** — 2 false positives / 121 clean events = 1.65%.
   Nếu được thấy answer key của Public, sẽ phân tích pattern của 2 FP này để
   điều chỉnh. Có thể do một signal riêng lẻ vượt baseline nhưng thực sự là
   normal variance — cần thêm margin nhỏ (ví dụ 5%) cho các threshold.

**Kết luận:** Chiến lược hiện tại cân bằng tốt giữa cost và coverage. Điểm yếu
lớn nhất là không có cơ chế học/tự điều chỉnh từ feedback — mỗi phase là một
lần chạy duy nhất, không có cơ hội sửa sai. Nếu được thiết kế lại, sẽ ưu tiên
cơ chế tự calibration dựa trên các event clean đầu tiên trong stream.

