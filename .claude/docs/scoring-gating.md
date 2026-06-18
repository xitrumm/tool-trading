# Logic lọc kèo, chấm điểm & trade plan

> Tài liệu chi tiết tách từ [CLAUDE.md](../CLAUDE.md). Đọc file này khi sửa `check_and_evaluate`, `compute_score`, `get_today_rank`, `build_trade_plan`, `format_trade_plan`.

## Logic lọc kèo (Người Gác Cổng V6 — `check_and_evaluate`)

```
Coin được nhắc ≥ 2 lần hôm nay (signals + money_flow)  HOẶC  nguồn khẩn cấp (Watchlist/Excel)
        │
        ▼
BƯỚC 1 — Soi kỹ thuật (Binance Spot):
        Giá đóng 4H > EMA25(4H)  VÀ  Giá đóng 1D > EMA25(1D)?
        ├─ KHÔNG → ❌ Loại, ghi XIT_KY_THUAT
        └─ CÓ ↓
BƯỚC 1.5 — Gác TP1 tối thiểu:
        TP1 (khung 4H) ≥ +10% so với entry?
        ├─ KHÔNG → 🔇 Loại SỚM, ghi XIT_TP_HEP (không qua BƯỚC 2/3, KHÔNG broadcast)
        └─ CÓ ↓
BƯỚC 2 — Quét vĩ mô + phái sinh (Binance Futures):
        • Thời tiết: BTC & ETH so với EMA25 ngày
          (cả 2 xanh = "NẮNG ĐẸP" / cả 2 gãy = "BÃO TỐ" / lệch nhau = "BIẾN ĐỘNG")
        • L/S Ratio, Funding Rate, Open Interest
        │
        ▼
        NẮNG ĐẸP  VÀ  L/S > 1.0  VÀ  RSI(1D) < 75 (chống FOMO)?
        ├─ CÓ  → 🌟 BUY_HOA_HAU_VIP (kèo VIP)
        └─ KHÔNG → ✅ BUY_HOA_HAU (kèo thường, pass kỹ thuật nhưng thiếu bonus vĩ mô)
        │
        ▼
BƯỚC 3 — Chấm điểm & xếp hạng (`compute_score` + `get_today_rank`):
        Điểm 0-100: nền 50 (pass kỹ thuật) ± các yếu tố: VIP, số lần nhắc trong DB,
        nguồn khẩn cấp, RSI vùng đẹp 45-65, L/S, Funding âm/nóng, EMA xếp tầng
        (giá > EMA7 > EMA25 > EMA99), thời tiết, giá chạy quá xa EMA25 (>15%) bị trừ.
        Hạng tính so với điểm cao nhất của các coin KHÁC đã chốt hôm nay.
        Hạng 1 (hoặc hạng 2 với điểm ≥ 70) = 🏆 TOP PICK.
        │
        ▼
Kèo chốt (cả VIP lẫn Thường) → broadcast NGAY (mỗi bot đích tự gửi qua Bot API tới DM chính chủ)
theo format gọn 3 dòng bên dưới. (Kèo XIT_KY_THUAT / XIT_TP_HEP chỉ ghi DB, KHÔNG gửi đi)
```

**Format tin kèo broadcast** (label: `🌟 KÈO VIP` khi đủ bonus vĩ mô / `✅ KÈO THƯỜNG` khi thiếu; riêng TOP PICK luôn được nâng nhãn thành `KÈO VIP` kể cả khi thiếu bonus vĩ mô, icon giữ theo loại thật 🌟/✅; **kèo từ Watchlist đột biến** dùng nhãn riêng `🌟/✅ Watchlist` — KHÔNG nâng nhãn lên `KÈO VIP` dù là TOP PICK; **kèo từ dòng tiền luân chuyển** dùng nhãn riêng 2 dòng `⚡ SMART MONEY ROTATION` + `💰 <từ> → <đích>`; dòng điểm `💯 Điểm: ...` nằm RIÊNG ngay dưới dòng nhãn; **riêng kèo từ Excel** có cột timeframe thì dòng stats cuối được nối thêm ` | TF: 4H` — chỉ trong tin broadcast này, không vào DB/`/stats`/báo cáo định kỳ):

Kèo thường:
```
✅ KÈO THƯỜNG: XPL
💯 Điểm: 60/100 (hạng 5 hôm nay)
📥 Entry: 0.086100 - SL: 0.077194 (-10.3%) - TP1: 0.099459 (+15.5%) | TP2: 0.112818 (+31.0%)
RSI: 53 | L/S: 0.75 | FR: 0.0050%
```

Top pick (thêm header 🏆):
```
🏆🏆🏆 TOP PICK 🏆🏆🏆
✅ KÈO VIP: TRUMP
💯 Điểm: 85/100 (hạng 1 hôm nay)
📥 Entry: 2.1950 - SL: 2.0415 (-7.0%) - TP1: 2.4253 (+10.5%) | TP2: 2.6556 (+21.0%)
RSI: 61 | L/S: 2.51 | FR: -0.1128%
```

## Entry / Stoploss / Take Profit (`BinanceRadar.build_trade_plan` — khung 4H)

- **Entry** = giá đóng nến 4H mới nhất (≈ giá hiện tại).
- **Stoploss** = min(swing low 20 nến 4H, EMA25 4H) − 0.5×ATR(14); nếu xa hơn −8% so với entry thì thay bằng entry − 2×ATR; tuyệt đối không vượt −8% (fallback cuối: entry × 0.95).
- **TP1 / TP2** = entry + 1.5×risk / entry + 3×risk (R:R cố định 1.5 và 3.0, risk = entry − SL).
- Giá hiển thị qua `fmt_price`: ≥100 → 2 số lẻ, ≥1 → 4, ≥0.01 → 6, còn lại 8 số lẻ.

## Trọng số chấm điểm (`compute_score` — nền 50, kẹp 0-100)

| Yếu tố | Điểm |
|---|---|
| Kèo VIP (đủ bộ vĩ mô) | +10 |
| Số lần nhắc trong DB hôm nay | +5 mỗi lần vượt mốc 2, tối đa +15 |
| Nguồn khẩn cấp (Watchlist/Excel) | +5 |
| RSI 1D trong vùng 45-65 / trên 75 | +10 / −10 |
| L/S Ratio > 1.5 / > 1.0 / < 0.8 | +5 / +3 / −5 |
| Funding âm / > 0.05% | +5 / −5 |
| EMA xếp tầng (giá > EMA7 > EMA25 > EMA99, khung 1D) | +10 |
| Thời tiết NẮNG ĐẸP / BÃO TỐ | +10 / −15 |
| Giá vượt EMA25(1D) quá 15% (đu đỉnh) | −5 |

Hạng (`get_today_rank`) so điểm với MAX điểm của từng coin KHÁC đã chốt hôm nay (lỗi DB trả hạng 99 để không tự nhận TOP PICK bừa). Kèo gửi sớm trong ngày không bị rút highlight nếu sau đó có kèo điểm cao hơn — nhưng báo cáo định kỳ và `/stats` luôn xếp hạng lại toàn cục.
