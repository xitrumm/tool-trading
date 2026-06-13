# CLAUDE.md

File này cung cấp ngữ cảnh cho Claude Code (claude.ai/code) khi làm việc với mã nguồn trong repo này.

## Tổng quan dự án

**Bot Trading "Siêu Megazord V6"** — bot lọc tín hiệu crypto chạy trên **tài khoản Telegram cá nhân** (userbot qua Telethon, KHÔNG dùng bot token). Luồng hoạt động:

1. **Nghe** tin nhắn đến từ MỘT bot nguồn duy nhất — cấu hình `SOURCE_BOT` (text + file Excel/CSV đính kèm).
2. **Bắt tín hiệu** coin theo 4 định dạng (xem mục "Định dạng tin nhắn bot nhận diện").
3. **Gom & kích hoạt**: khi 1 coin được nhắc ≥ 2 lần trong ngày (hoặc nguồn khẩn cấp) → chạy phân tích sâu.
4. **Đối chiếu Binance**: kỹ thuật (EMA 7/25/99, RSI), thời tiết thị trường (BTC+ETH), phái sinh (L/S Ratio, Funding Rate, Open Interest).
5. **Phân hạng kèo**: VIP (🌟) / Thường (✅) / Loại — Xịt (❌), lưu vào SQLite.
6. **Chấm điểm & chọn TOP PICK**: mỗi kèo chốt được chấm 0-100 điểm, xếp hạng so với các kèo khác trong ngày; hạng 1 (hoặc hạng 2 điểm ≥ 70) gắn 🏆 TOP PICK.
7. **Phát kèo real-time**: kèo chốt (VIP/Thường) broadcast NGAY — **mỗi bot đích RELAY** tin qua Bot API (token) tới TẤT CẢ người đã đăng ký bot đó (người từng /start hoặc nhắn bot — chat_id thu thập qua `getUpdates`, lưu bảng `bot_subscribers`), kèm điểm + hạng + Entry/Stoploss/TP1/TP2.
8. **Báo cáo & backup tự động**: báo cáo gửi vào Saved Messages + relay qua tất cả bot đích tới subscriber của chúng 2 lần/ngày, backup DB lên Google Drive 2 lần/ngày.
9. **Chống mất dữ liệu khi tool tắt**: lúc khởi động tự đọc bù tin nhắn bị lỡ của bot nguồn và gửi bù báo cáo nếu offline qua mốc 07:00/16:00 (trạng thái lưu trong bảng `bot_state`).
10. **ML shadow mode** (xem mục "Khối ML"): model ML chấm xác suất kèo chạm TP1 trước SL hiển thị SONG SONG với điểm rule (không can thiệp quyết định); radar IsolationForest tự quét coin có volume/giá bất thường làm nguồn tín hiệu thứ 2; mọi kèo phát ra được tự động chấm kết quả thắng/thua để tích lũy dữ liệu huấn luyện.

```
SOURCE_BOT (1 bot nguồn) → lọc 3 bước + Binance → n bot đích relay (Bot API → subscriber từng bot) + Saved Messages
```

## ⚠️ Trạng thái mã nguồn (QUAN TRỌNG)

- **File chạy chính thức: `bottrading.py`** — mọi chỉnh sửa code thực hiện trên file này.
- `bottrading.txt` là bản dán gốc (bị lặp 2 lần cùng một nội dung), chỉ giữ để tham khảo — KHÔNG sửa/chạy file này, có thể xóa khi không cần.
- Cấu hình KHÔNG nằm trong code mà đọc từ 2 file ngoài (cùng thư mục với `bottrading.py`):
  - `config.txt` — `API_ID`, `API_HASH` (lấy từ https://my.telegram.org) và `SOURCE_BOT` (bot nguồn), dạng `KEY=VALUE`. **Chứa secret thật → đã gitignore.**
  - `target_bots.txt` — danh sách **token** bot đích (lấy từ @BotFather, dạng `123456789:ABC...`), mỗi dòng 1 token, dòng `#` là comment. Mỗi bot dùng token này để TỰ gửi report qua Bot API. **Chứa secret thật (token) → đã gitignore.**
- Trên máy hiện tại cả 2 file **đã điền giá trị thật** (đã chạy thật, có `megazord_session.session` + `trading_memory.db`). Khi setup máy mới: phải tự điền — thiếu file / thiếu giá trị → bot in lỗi tiếng Việt rõ ràng và thoát ngay lúc khởi động (`SystemExit` trong `load_config` / `load_target_bots`).
- Nơi backup DB chọn tự động qua `get_backup_dir()`: ưu tiên `G:\My Drive\Trading_Bot` (Google Drive for desktop mount ổ G:), nếu ổ G: chưa mount thì fallback sang `Desktop\Trading_Bot` (có xử lý cả trường hợp Desktop bị OneDrive chuyển hướng).

## Cài đặt & Chạy

```powershell
# 1. Cài dependencies (Python 3.9+ — scikit-learn yêu cầu; bot core không ML chạy được 3.8)
pip install -r requirements.txt

# 2. Mở config.txt — điền API_ID, API_HASH thật (my.telegram.org → API development tools)
#    và SOURCE_BOT (@username hoặc ID số của bot nguồn cần đọc)

# 3. Mở target_bots.txt — mỗi dòng 1 TOKEN bot đích (lấy từ @BotFather), thêm "#tên" để dễ nhớ
#    Mỗi bot relay tin tới những người đã /start CHÍNH bot đó (tool gom chat_id qua getUpdates).
#    → Người tạo bot / người nhận phải /start bot khi tool ĐANG CHẠY thì mới được thu thập.

# 4. Chạy bot
python bottrading.py
```

**Lần chạy đầu tiên**: Telethon sẽ hỏi số điện thoại → mã OTP gửi qua Telegram → mật khẩu 2FA (nếu có). Sau đó tạo file `megazord_session.session` — **giữ bí mật file này** (ai có nó là đăng nhập được tài khoản), không commit lên git.

Bot chạy đến khi mất kết nối / Ctrl+C (`run_until_disconnected`). Khi khởi động in dòng `🚀 SIÊU MEGAZORD V6 ĐÃ LÊN NÒNG!` và backup DB ngay 1 lần.

### Kiểm tra tool hoạt động (lần đầu chạy)

1. **Console**: phải in `🚀 SIÊU MEGAZORD V6 ĐÃ LÊN NÒNG!` + dòng `📡 Nguồn vào: ... | 📤 Relay qua N bot tới subscriber...` → đăng nhập & nạp config thành công.
2. **Gõ `/stats` trong Saved Messages**: tool trả lời ngay (kể cả khi chưa có dữ liệu) → chứng tỏ đang nghe và gửi được.
3. **Gõ `/test`**: kiểm tra Binance Spot/Futures, SQLite, và TỪNG bot đích (getMe xác thực token + đếm người đăng ký). Sau đó nhờ người tạo bot /start bot khi tool đang chạy → gõ `/subs` thấy họ xuất hiện trong danh sách.
4. **Test luồng thật**: làm bot nguồn gửi tin dạng Watchlist (được đánh giá NGAY, không cần đủ 2 lần nhắc) → console in `🚨 KÍCH HOẠT MẮT THẦN V6` + các subscriber của bot đích nhận kèo nếu pass kỹ thuật. Lưu ý: tin phải do CHÍNH bot nguồn gửi đến — tự gõ vào chat đó không kích hoạt (filter `incoming=True`).
5. **Kiểm tra khối ML**: console lúc khởi động phải in dòng `🤖 ML shadow: ...` (có model → version + AUC; chưa có → "chế độ THU THẬP DỮ LIỆU"). Gõ `/ml` xem số mẫu; gõ `/radar` quét tay 1 lượt (~1 phút, trả về coin lạ hoặc "không có gì lạ"; gõ lần 2 ngay sau đó phải báo "đã cảnh báo trong 24h" → dedupe chạy đúng; gõ `/stats` GIỮA lúc quét phải được trả lời ngay → event loop không nghẽn).

## Cách sử dụng chi tiết

### Lệnh điều khiển (chỉ nhận tin do CHÍNH tài khoản đang chạy bot gõ ra — filter `outgoing=True`)

Gõ vào bất kỳ chat nào từ tài khoản của bạn (tiện nhất là **Saved Messages**):

| Lệnh | Tác dụng |
|---|---|
| `/stats` | Trả về báo cáo dòng tiền tổng hợp trong ngày (top ngành hút tiền, 🏆 top 1-2 kèo đáng giá nhất kèm Entry/SL/TP, các kèo Hoa Hậu khác xếp theo điểm giảm dần, kèo rác đã chặn) |
| `/backup` | Copy `trading_memory.db` lên Google Drive ngay (ổ G: chưa mount → lưu `Desktop\Trading_Bot`); trả lời kèm đường dẫn đã lưu |
| `/test` | Tự kiểm tra: Binance Spot/Futures, SQLite, và TỪNG bot đích (gọi `getMe` xác thực token + đếm số người đăng ký) — KHÔNG gửi tin tới subscriber để tránh spam |
| `/subs` | Quét ngay (`getUpdates`) & liệt kê người đăng ký theo từng bot đích (số người + tên) |
| `/ml` | Trạng thái ML: version model + AUC, số mẫu live/backfill, win rate thực tế, số kèo chờ chấm kết quả, lần chạy job gần nhất |
| `/radar` | Quét radar coin bất thường NGAY (thay vì chờ lịch 4h) — trả về danh sách coin lạ hoặc "không có gì lạ" |

### Định dạng tin nhắn bot nhận diện (CHỈ đọc từ `SOURCE_BOT`)

**1. Tín hiệu BUY dạng text** (chỉ ghi nhận direction BUY, bỏ qua SELL):
```
symbol: SOL/USDT | direction: BUY | timeframe: 4h
```
→ Ghi `RAW_SIGNAL`, cộng dồn đếm tín hiệu cho coin đó.

**2. Dòng tiền luân chuyển** (bắt buộc dùng mũi tên `→` U+2192):
```
BTC → SOL
```
→ Ghi vào bảng `money_flow`, coin đích (SOL) được cộng đếm và đánh giá.

**3. Watchlist đột biến** (tin nhắn chứa cả chữ `Watchlist` và `Mới thêm`, coin nằm sau dấu `•` và trước dấu `—` hoặc `-`):
```
Watchlist Mới thêm:
• SOL — volume tăng đột biến
• AVAX - breakout
```
→ Ghi `RAW_URGENT` và **đánh giá NGAY** (force_urgent, bỏ qua điều kiện ≥ 2 lần nhắc).

**3b. Cảnh báo nhanh Capital Convergence** (tin chứa `Capital Convergence`, dòng dạng `• ENJ — Capital Convergence: <lý do>`): NGOÀI luồng RAW_URGENT ở trên, mỗi coin còn đi qua `convergence_alert` — chạy TRƯỚC gác cổng để cảnh báo ngay lập tức:
- Soi ngay khung 1H + 4H (`BinanceRadar.analyze_convergence` — 2 call klines), KHÔNG qua gác cổng EMA và KHÔNG ghi bảng `signals` (tránh cộng lượt nhắc ảo).
- Điều kiện bắn: |biến động giá 24h| < 10% **HOẶC** giá còn nằm trong dải Bollinger MA99 (SMA99 ± 2σ) khung 1H — coin đã pump quá thì im lặng (chỉ log console).
- Entry = giá đóng 1H mới nhất; TP1 = kháng cự (pivot high cửa sổ 3-3) 1H gần nhất phía trên, tối thiểu +1% (không có → +3%); TP2 = kháng cự 4H nằm trên TP1 (không có → +6%); SL = hỗ trợ (pivot low) 1H gần nhất phía dưới, tối thiểu −1%, hỗ trợ xa hơn −8% thì lùi về −5%.
- Format broadcast (mỗi bot đích tự gửi qua Bot API):
```
👀Capital Convergence
✅ENJ: Nhiều nguồn vốn cùng chảy về 1 coin
📥 Entry: xx - SL: xx (-xx%) - TP1: xx (+xx%) | TP2: xx (+xx%)
```

**4. File Excel/CSV đính kèm**: cần có cột chứa chữ `SYMBOL` hoặc `COIN`, và cột chứa chữ `PRIORITY` hoặc `SCORE` (không phân biệt hoa thường). Mọi dòng có điểm **> 70** sẽ được ghi `RAW_EXCEL` và **đánh giá NGAY**. File tạm `temp_data.xlsx` tự xóa sau xử lý.

### Logic lọc kèo (Người Gác Cổng V6 — `check_and_evaluate`)

```
Coin được nhắc ≥ 2 lần hôm nay (signals + money_flow)  HOẶC  nguồn khẩn cấp (Watchlist/Excel)
        │
        ▼
BƯỚC 1 — Soi kỹ thuật (Binance Spot):
        Giá đóng 4H > EMA25(4H)  VÀ  Giá đóng 1D > EMA25(1D)?
        ├─ KHÔNG → ❌ Loại, ghi XIT_KY_THUAT
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
theo format gọn 3 dòng bên dưới. (Kèo XIT_KY_THUAT chỉ ghi DB, KHÔNG gửi đi)
```

**Format tin kèo broadcast** (label: `🌟 KÈO VIP` khi đủ bonus vĩ mô / `✅ KÈO THƯỜNG` khi thiếu; riêng TOP PICK luôn được nâng nhãn thành `KÈO VIP` kể cả khi thiếu bonus vĩ mô, icon giữ theo loại thật 🌟/✅; nếu có model ML thì dòng `🤖 ML: xx%...` chèn sau dòng đầu):

Kèo thường:
```
✅ KÈO THƯỜNG: XPL - Điểm: 60/100 (hạng 5 hôm nay)
📥 Entry: 0.086100 - SL: 0.077194 (-10.3%) - TP1: 0.099459 (+15.5%) | TP2: 0.112818 (+31.0%)
RSI: 53 | L/S: 0.75 | FR: 0.0050%
```

Top pick (thêm header 🏆):
```
🏆🏆🏆 TOP PICK 🏆🏆🏆
✅ KÈO VIP: TRUMP - Điểm: 85/100 (hạng 1 hôm nay)
📥 Entry: 2.1950 - SL: 2.0415 (-7.0%) - TP1: 2.4253 (+10.5%) | TP2: 2.6556 (+21.0%)
RSI: 61 | L/S: 2.51 | FR: -0.1128%
```

### Entry / Stoploss / Take Profit (`BinanceRadar.build_trade_plan` — khung 4H)

- **Entry** = giá đóng nến 4H mới nhất (≈ giá hiện tại).
- **Stoploss** = min(swing low 20 nến 4H, EMA25 4H) − 0.5×ATR(14); nếu xa hơn −8% so với entry thì thay bằng entry − 2×ATR; tuyệt đối không vượt −8% (fallback cuối: entry × 0.95).
- **TP1 / TP2** = entry + 1.5×risk / entry + 3×risk (R:R cố định 1.5 và 3.0, risk = entry − SL).
- Giá hiển thị qua `fmt_price`: ≥100 → 2 số lẻ, ≥1 → 4, ≥0.01 → 6, còn lại 8 số lẻ.

### Trọng số chấm điểm (`compute_score` — nền 50, kẹp 0-100)

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

### Khối ML (Shadow Mode) — thêm từ 06/2026

**Nguyên tắc**: ML chỉ QUAN SÁT, không can thiệp — kèo vẫn lọc/chấm/xếp hạng bằng rule như cũ; model chỉ thêm dòng `🤖 ML: xx% khả năng chạm TP1 trước SL` vào tin kèo. Bot chạy được Y HỆT bản cũ nếu thiếu model/sklearn (mọi import + khối ML đều guard).

**File**: `ml_features.py` (nguồn chân lý: 28 feature giá/volume, trade plan, gán nhãn `walk_label`, DDL — dùng chung live & backfill để không lệch train/serve), `ml_predict.py` (load `models/signal_model.pkl`, thiếu → trả None), `ml_radar.py` (IsolationForest quét cross-section ~150 coin, guard cứng volume ≥3× + giá 24h dương), `backfill_dataset.py` (CLI tạo dataset lịch sử), `train_model.py` (CLI train purged walk-forward + calibrate).

**Vòng đời dữ liệu**: mỗi kèo chốt → ghi 1 dòng `ml_samples` (source='live', đủ 28 feature + extras phái sinh/mention) → job 6h/lần chấm kết quả (TP1 trước SL trước, horizon 14 ngày, nến mơ hồ tính thua) → đủ ≥300 mẫu live thì train lại model v2 (`--source backfill,live`).

**📌 TRẠNG THÁI HIỆN TẠI (12/06/2026)**: dataset backfill **900 ngày (8.009 mẫu / 150 coin, win rate 38.8%) ĐÃ nằm sẵn trong `trading_memory.db`** — không cần chạy lại backfill trừ khi đổi công thức. Model v1 đã train 2 lần (540 → 900 ngày) nhưng **RỚT ngưỡng ship** (AUC walk-forward 0.541 < 0.56, dù đã hơn rule baseline 0.499 và calibration đơn điệu đạt) → **CHƯA có `models/signal_model.pkl`**, tin kèo CHƯA có dòng 🤖. Pipeline đã kiểm chứng sạch bằng shuffle-test (phá nhãn → AUC sập về ~0.5). Bot đang ở **chế độ thu thập dữ liệu**: mọi kèo chốt được log feature + tự chấm thắng/thua chờ train v2.

**Hướng dẫn sử dụng hằng ngày**:

| Việc | Cách làm |
|---|---|
| Chạy bot | `python bottrading.py` như cũ — console in `🤖 ML shadow: chưa có model — chế độ THU THẬP DỮ LIỆU` là đúng trạng thái |
| Xem ML đang tích lũy gì | Gõ `/ml` ở Saved Messages: số mẫu live/backfill, win rate thực tế, kèo chờ chấm, lần chạy job |
| Quét coin lạ ngay | Gõ `/radar` (radar vẫn chạy tự động 4h/lần dù chưa có model — không phụ thuộc model chấm điểm) |
| Bật cảnh báo radar tới bot đích | Sửa `RADAR_NOTIFY_TARGETS = True` đầu file `bottrading.py` (mặc định chỉ gửi Saved Messages) |

**Quy trình train v2 (khi đủ điều kiện)** — điều kiện: `/ml` báo **≥ 300 mẫu live đã có kết quả** (ước tính vài tháng chạy bot):
```powershell
python train_model.py --source backfill,live   # train trộn lịch sử + kèo thật
# Ngưỡng ship: AUC >= 0.56 VÀ hơn rule baseline +0.02 VÀ calibration đơn điệu.
# ĐẠT → tự ghi models/signal_model.pkl → restart bot → tin kèo có dòng "🤖 ML: xx% khả năng chạm TP1 trước SL"
# RỚT → script exit lỗi, KHÔNG ghi model. --force chỉ dành cho thử nghiệm pipeline, ĐỪNG dùng cho chạy thật.
```

**Radar**: chạy 4h/lần (03:10, 07:10, ... giờ VN — ngay sau nến 4H đóng), coin lạ được cảnh báo vào Saved Messages (broadcast bot đích tắt mặc định — hằng số `RADAR_NOTIFY_TARGETS`), ghi 1 dòng `signals` type `RAW_RADAR` = **tính 1 lượt nhắc** rồi đi qua đúng pipeline gác cổng KHÔNG force_urgent → radar đơn độc không bao giờ tự chốt kèo, cần nguồn khác nhắc cùng ngày mới đủ ngưỡng 2 lượt. Dedupe 24h/coin qua bảng `anomaly_alerts`. Đã test thật 12/06/2026: bắt được UTK (volume ×23, +16%), HMSTR (+50%, volume ×8.5).

**Lưu ý khi sửa**: model v1 CHỈ train trên 28 feature giá/volume (Binance không giữ lịch sử L/S, OI quá ~30 ngày nên backfill không tái lập được feature phái sinh — chúng vẫn được log ở live làm nhiên liệu cho v2). KHÔNG thêm feature lịch (giờ/thứ) — backfill bước theo daily close còn live nổ bất kỳ lúc nào, feature lịch sẽ leak nguồn gốc mẫu. **Đổi công thức feature/nhãn trong `ml_features.py` thì PHẢI xóa mẫu backfill cũ rồi chạy lại** (`DELETE FROM ml_samples WHERE source='backfill'` — vì backfill dùng INSERT OR IGNORE theo khóa (source, coin, ts) nên chạy lại KHÔNG tự đè dòng cũ), sau đó train lại. Khi đánh giá model, KHÔNG BAO GIỜ dùng shuffle split — nhãn nhìn 14 ngày tương lai, chỉ dùng purged walk-forward có sẵn trong `train_model.py`.

### Lịch tự động (timezone Asia/Ho_Chi_Minh, APScheduler)

| Giờ | Việc |
|---|---|
| 07:00 | Gửi "Bản tin điểm tâm VIP" vào Saved Messages + tất cả bot đích |
| 16:00 | Gửi báo cáo chiều vào Saved Messages + tất cả bot đích |
| 11:55 | Backup DB (Google Drive, fallback Desktop) |
| 23:55 | Backup DB (Google Drive, fallback Desktop) |
| 01:20, 07:20, 13:20, 19:20 | Job ML: chấm kết quả (TP/SL) các kèo live đang chờ trong `ml_samples` |
| 03:10, 07:10, 11:10, 15:10, 19:10, 23:10 | Radar ML quét coin bất thường (chạy trong thread riêng, không nghẽn bot) |
| Mỗi 2 phút (interval) | `poll_subscribers_job`: getUpdates từng bot đích, cập nhật `bot_subscribers` (bắt người mới /start) |

### Đọc bù & gửi bù khi khởi động (chống mất dữ liệu lúc tool tắt)

Mỗi lần khởi động, TRƯỚC khi vào vòng lặp chính, tool chạy 2 bước theo thứ tự:

1. **`catch_up_source_messages()` — đọc bù tin nhắn**: lấy `last_msg_id` (ID tin cuối đã xử lý, lưu trong bảng `bot_state`) rồi kéo mọi tin bot nguồn gửi SAU mốc đó qua `iter_messages(min_id=..., reverse=True)`, lọc bỏ tin do mình gõ (`if not m.out`), xử lý từng tin bằng đúng pipeline thường (`process_source_message`). Tin đọc bù dùng **giờ gửi gốc của tin** (đổi sang giờ VN) nên đếm số lần nhắc vẫn đúng ngày. Giới hạn an toàn: tối đa 300 tin mới nhất (lỡ nhiều hơn thì bỏ phần cũ, có log). Lần chạy đầu tiên (chưa có mốc) chỉ ghi mốc, KHÔNG cày lại lịch sử.
2. **`catch_up_missed_report()` — gửi bù báo cáo**: so `last_report_sent` (bảng `bot_state`) với mốc báo cáo 07:00/16:00 gần nhất đã qua (`_last_due_report_time`); nếu tool offline qua mốc đó → gửi ngay 1 báo cáo có header "⏰ BÁO CÁO GỬI BÙ" vào Saved Messages + mọi bot đích. Chạy SAU bước đọc bù nên báo cáo đã gồm các kèo vừa đọc bù.

`last_msg_id` được cập nhật sau MỖI tin xử lý xong (khối `finally` của `process_source_message`); `last_report_sent` cập nhật sau mỗi lần `auto_send_report` chạy (kể cả theo lịch cron).

### Database (`trading_memory.db` — SQLite, tự tạo khi chạy)

```sql
signals    (date TEXT, coin TEXT, timeframe TEXT, type TEXT,
            score REAL, entry REAL, stoploss REAL, tp1 REAL, tp2 REAL)
money_flow (date TEXT, sector_from TEXT, sector_to TEXT)
bot_state  (key TEXT PRIMARY KEY, value TEXT)   -- last_msg_id, last_report_sent, last_label_run, last_radar_scan, last_subs_poll, gu_offset_<bot_id>
bot_subscribers (bot_id TEXT, chat_id INTEGER, name TEXT, first_seen TEXT,
            PRIMARY KEY(bot_id, chat_id))        -- người đã /start mỗi bot đích (getUpdates thu thập) → đích relay
-- Bảng ML (DDL nằm trong ml_features.ML_DDL, init_db chạy tự động):
ml_samples (id PK, ts, coin, source 'live'|'backfill', features_json, entry, sl, tp1, tp2,
            rule_score, ml_prob, model_version,
            outcome 1|0|NULL, outcome_detail 'TP1'|'TP2'|'SL'|'AMBIGUOUS_SL'|'TIMEOUT'|'EXPIRED_NO_DATA',
            realized_r, resolved_at)            -- unique(source, coin, ts) → backfill idempotent
anomaly_alerts (id PK, ts, coin, anomaly_score, features_json)  -- radar, dedupe 24h/coin
```

Bảng `bot_state` (đọc/ghi qua `get_state`/`set_state`) gồm các key: `last_msg_id` (ID tin nhắn cuối của bot nguồn đã xử lý — mốc đọc bù), `last_report_sent` (ISO datetime lần gửi báo cáo định kỳ cuối — mốc gửi bù), `last_label_run` và `last_radar_scan` (ISO datetime lần chạy job ML gần nhất — hiển thị trong `/ml`), `last_subs_poll` (lần quét getUpdates gần nhất), và `gu_offset_<bot_id>` (offset getUpdates đã xác nhận cho từng bot đích — để lần sau chỉ lấy update mới).

**Cơ chế subscriber bot đích** (`bot_subscribers`): mỗi bot đích là bot do người khác tạo và đưa token cho mình; tool gọi `getUpdates` định kỳ (job `interval` 2 phút + 1 lần lúc khởi động) cho từng token, gom mọi `chat.id` private nhắn bot → lưu vào `bot_subscribers`. Khi broadcast, mỗi bot relay tin tới TẤT CẢ subscriber của nó; ai block/xoá bot (`sendMessage` trả `blocked`/`deactivated`/`chat not found`) bị `remove_subscriber` gỡ tự động. **Giới hạn Telegram: getUpdates chỉ giữ update ~24h** → người /start từ lâu mà không nhắn lại sẽ KHÔNG bắt được; cần họ nhắn /start lại khi tool đang chạy. `getUpdates` cũng xung đột nếu bot đó đang đặt webhook (trả lỗi rõ trong log/`/test`).

5 cột cuối của `signals` chỉ có giá trị với kèo chốt (`BUY_HOA_HAU%`); tín hiệu thô để NULL. DB cũ tự migrate bằng `ALTER TABLE` trong `init_db` (lỗi "duplicate column" được nuốt). `insert_db` nhận tham số `columns` để insert đúng cột — mọi insert vào `signals` PHẢI truyền `columns`.

Các giá trị `type` trong bảng `signals`:

| Type | Ý nghĩa |
|---|---|
| `RAW_SIGNAL` | Tín hiệu BUY thô từ text |
| `RAW_URGENT` | Coin từ Watchlist đột biến |
| `RAW_EXCEL` | Coin từ file Excel/CSV (score > 70) |
| `BUY_HOA_HAU` | Pass kỹ thuật EMA 4H/1D (cột `timeframe` chứa chuỗi stats: RSI, L/S, FR) |
| `BUY_HOA_HAU_VIP` | Pass kỹ thuật + đủ bonus vĩ mô |
| `XIT_KY_THUAT` | Bị loại vì cấu trúc giá yếu (dưới EMA25) |
| `RAW_RADAR` | Coin do radar ML phát hiện bất thường (tính 1 lượt nhắc, không tự chốt kèo) |

Báo cáo `/stats` chỉ thống kê dữ liệu **trong ngày hiện tại** (lọc `date LIKE 'YYYY-MM-DD%'`).

## Kiến trúc file (7 khối, theo comment trong code; khối ML nằm ở 5 file `ml_*.py` / `backfill_dataset.py` / `train_model.py` riêng)

| Khối | Thành phần | Vai trò |
|---|---|---|
| 1. Cấu hình | `load_config` (đọc `config.txt`), `load_target_bots` (đọc token + nhãn từ `target_bots.txt`), `_parse_entity`, `client`, `_bot_api`, `_send_via_bot`, `broadcast_to_bots` | Nạp API_ID/API_HASH/SOURCE_BOT + TOKEN bot đích từ file ngoài, khởi tạo Telethon session `megazord_session` (nguồn vào) + gửi ra qua Bot API (mỗi bot relay tới subscriber của nó) |
| 2. Quant Engine | class `BinanceRadar` (`get_klines`, `calculate_ema`, `calculate_rsi`, `calculate_atr`, `build_trade_plan`, `find_pivot_levels`, `analyze_convergence`, `check_market_weather`, `spy_on_derivatives`, `analyze_coin`) | Gọi Binance API: klines, EMA, RSI, ATR, thời tiết BTC/ETH, phái sinh (L/S, FR, OI) + tính Entry/SL/TP1/TP2 khung 4H + soi nhanh 1H/4H (pivot kháng cự/hỗ trợ, Bollinger MA99) cho cảnh báo Capital Convergence |
| 3. Lưu trữ | `init_db` (kèm migrate + DDL ML), `insert_db`, `get_state`, `set_state`, `_upsert_subscriber`/`get_subscribers`/`remove_subscriber`, `_poll_subscribers_worker`/`poll_subscribers_job`, `get_backup_dir`, `backup_to_drive` | SQLite (6 bảng: signals, money_flow, bot_state, bot_subscribers, ml_samples, anomaly_alerts) + thu thập subscriber bot đích qua getUpdates + trạng thái đọc bù/gửi bù + copy DB sang Google Drive (fallback Desktop khi ổ G: chưa mount) |
| 4. Báo cáo | `generate_report` | Tổng hợp dòng tiền, 🏆 top 1-2 kèo điểm cao nhất (kèm Entry/SL/TP), các kèo Hoa Hậu khác xếp theo điểm, kèo rác trong ngày |
| 5. Gác cổng | `fmt_price`, `compute_score`, `get_today_rank`, `format_trade_plan`, `check_and_evaluate`, `process_source_message`, `main_handler`, `command_handler` | Lọc kèo 3 bước (kỹ thuật → vĩ mô/phái sinh → chấm điểm & xếp hạng) + parse 4 định dạng (chỉ từ bot nguồn, dùng chung cho real-time & đọc bù) + lệnh `/stats`, `/backup`, `/test`, `/subs` |
| 5.5. ML Shadow | `_label_worker`, `label_pending_samples_job`, `radar_scan_job`, `build_ml_status` (+ module ngoài: `ml_features`, `ml_predict`, `ml_radar`) | Chấm kết quả kèo live, radar coin lạ, lệnh `/ml` `/radar`; khối dự đoán nằm trong `check_and_evaluate` BƯỚC 3.5 |
| 6. Khởi chạy | `catch_up_source_messages`, `_last_due_report_time`, `catch_up_missed_report`, `auto_send_report`, `main` | Đọc bù tin lỡ + gửi bù báo cáo lúc khởi động, APScheduler cron jobs, vòng lặp chính |

## Lưu ý kỹ thuật khi sửa code

- **Userbot cho NGUỒN VÀO + Bot API cho ĐẦU RA (hybrid)**: tài khoản cá nhân (Telethon) chỉ dùng để NGHE `SOURCE_BOT` — `events.NewMessage(chats=SOURCE_BOT, incoming=True)` (muốn nghe thêm nhiều nguồn, đổi thành list `chats=[bot1, bot2]`). Khâu PHÁT ra ngoài KHÔNG dùng userbot mà gọi **Bot API** (`_bot_api`/`_send_via_bot` → `api.telegram.org/bot<TOKEN>/...`): mỗi bot đích relay report tới subscriber của chính nó (xem "Cơ chế subscriber bot đích" ở mục Database). Lý do: bot không thể nhắn cho bot khác, nên chỉ tài khoản cá nhân mới NGHE được bot nguồn; nhưng để tin xuất hiện DO bot đích đăng (tới đúng người dùng của bot đó) thì phải dùng token của chúng.
- **Timestamp tin nhắn lấy theo giờ GỬI** (`message.date` đổi sang `VN_TZ`), không phải giờ xử lý — để tin đọc bù được ghi đúng ngày. Khi sửa logic thời gian, dùng `VN_TZ` (global), tránh `datetime.now()` trần.
- **Đọc bù có thể trùng 1 tin**: `last_msg_id` ghi sau khi xử lý xong; nếu tool chết GIỮA LÚC đang xử lý 1 tin, tin đó sẽ được xử lý lại khi khởi động (coin bị đếm 2 lần) — chấp nhận được, hiếm gặp.
- **Người nhận phải /start bot đích trước**: Bot API chỉ cho bot nhắn tới user đã từng bắt chuyện với nó. Tool KHÔNG tự biết ai đã /start — phải `getUpdates` gom `chat_id` rồi mới gửi được (xem "Cơ chế subscriber"). `broadcast_to_bots` lặp `TARGET_BOT_TOKENS` → với mỗi bot lấy `get_subscribers(bot_id)` rồi gọi `_send_via_bot` cho từng người trong `asyncio.to_thread` (không nghẽn event loop), giãn 0.05s/người; lỗi `blocked`/`deactivated`/`chat not found` → `remove_subscriber` gỡ người đó. Token là secret → chỉ in nhãn tên bot (`label`), KHÔNG bao giờ in token/`bot_id` đầy đủ ra log.
- **Lệnh /stats, /backup** bắt qua handler riêng `events.NewMessage(outgoing=True)` — chỉ tin nhắn do CHÍNH bạn gõ, ở bất kỳ chat nào.
- **Blocking trong async**: `check_and_evaluate` (đã chuyển sang `async def`) vẫn dùng `requests` đồng bộ bên trong → block event loop khi phân tích (mỗi coin tốn ~6-8 HTTP call). Nếu tối ưu, cân nhắc `asyncio.to_thread` hoặc `aiohttp`.
- **Nuốt lỗi**: nhiều chỗ `except: pass` / trả giá trị mặc định (`spy_on_derivatives` lỗi trả `1.0, 0.0, 0.0` — L/S=1.0 có thể làm sai điều kiện VIP). Khi debug nên thêm log trước.
- **Binance API không cần key** (toàn endpoint public) nhưng có rate limit — tránh spam `analyze_coin`.
- **SQL dùng f-string cho ngày** trong `generate_report`/`check_and_evaluate` — chuỗi ngày do bot tự sinh nên không phải injection từ ngoài, nhưng giữ đúng format `YYYY-MM-DD HH:MM:SS` khi sửa.
- `numpy` được import nhưng không dùng trực tiếp (pandas cần nó ngầm).
- Coin symbol tự động ghép `USDT` khi gọi Binance (`{coin}USDT`) — chỉ hỗ trợ cặp USDT.
- File config đọc bằng `encoding='utf-8-sig'` để chấp nhận cả file lưu từ Notepad (UTF-8 có BOM). ID số trong config tự chuyển sang `int` qua `_parse_entity` (Telethon yêu cầu ID là số nguyên).
- Không commit: `config.txt` (chứa API_HASH thật), `target_bots.txt` (chứa TOKEN bot — secret), `megazord_session.session`, `trading_memory.db`, `temp_data.xlsx`, `models/` + `*.pkl` (model ML — tạo lại được bằng train_model.py) — `.gitignore` đã chặn sẵn các file này.
- **Job ML chạy nặng phải qua `asyncio.to_thread`**: radar quét ~150 request/lượt và labeler fetch nến theo lô — cả 2 đã chạy trong thread riêng để không nghẽn event loop Telegram (khác với `check_and_evaluate` cũ vẫn block — xem mục Blocking ở trên). Code ML mới nên giữ nguyên pattern này.
