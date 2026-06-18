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

```
SOURCE_BOT (1 bot nguồn) → lọc 3 bước + Binance → n bot đích relay (Bot API → subscriber từng bot) + Saved Messages
```

## ⚠️ Trạng thái mã nguồn (QUAN TRỌNG)

- **File chạy chính thức: `bottrading.py`** — mọi chỉnh sửa code thực hiện trên file này.
- `bottrading.txt.old` là bản dán gốc (bị lặp 2 lần cùng một nội dung), chỉ giữ để tham khảo — KHÔNG sửa/chạy file này, có thể xóa khi không cần.
- Cấu hình KHÔNG nằm trong code mà đọc từ 2 file ngoài (cùng thư mục với `bottrading.py`):
  - `config.txt` — `API_ID`, `API_HASH` (lấy từ https://my.telegram.org) và `SOURCE_BOT` (bot nguồn), dạng `KEY=VALUE`. **Chứa secret thật → đã gitignore.**
  - `target_bots.txt` — danh sách **token** bot đích (lấy từ @BotFather, dạng `123456789:ABC...`), mỗi dòng 1 token, dòng `#` là comment. Mỗi bot dùng token này để TỰ gửi report qua Bot API. **Chứa secret thật (token) → đã gitignore.**
- Trên máy hiện tại cả 2 file **đã điền giá trị thật** (đã chạy thật, có `megazord_session.session` + `trading_memory.db`). Khi setup máy mới: phải tự điền — thiếu file / thiếu giá trị → bot in lỗi tiếng Việt rõ ràng và thoát ngay lúc khởi động (`SystemExit` trong `load_config` / `load_target_bots`).
- Nơi backup DB chọn tự động qua `get_backup_dir()`: ưu tiên `G:\My Drive\Trading_Bot` (Google Drive for desktop mount ổ G:), nếu ổ G: chưa mount thì fallback sang `Desktop\Trading_Bot` (có xử lý cả trường hợp Desktop bị OneDrive chuyển hướng).

## Cài đặt & Chạy

```powershell
# 1. Cài dependencies (Python 3.9+ — dùng asyncio.to_thread)
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

## Cách sử dụng chi tiết

### Lệnh điều khiển (chỉ nhận tin do CHÍNH tài khoản đang chạy bot gõ — filter `outgoing=True` + **CHỈ trong Saved Messages**)

Gõ trong **Saved Messages** (chat với chính mình). Lệnh gõ ở chat khác bị bỏ qua (handler chặn `event.chat_id != MY_ID`):

| Lệnh | Tác dụng |
|---|---|
| `/stats` | Trả về báo cáo dòng tiền tổng hợp trong ngày (top ngành hút tiền, 🏆 top 1-2 kèo đáng giá nhất kèm Entry/SL/TP, các kèo Hoa Hậu khác xếp theo điểm giảm dần, các kèo đã bỏ qua) |
| `/backup` | Copy `trading_memory.db` lên Google Drive ngay (ổ G: chưa mount → lưu `Desktop\Trading_Bot`); trả lời kèm đường dẫn đã lưu |
| `/test` | Tự kiểm tra: Binance Spot/Futures, SQLite, và TỪNG bot đích (gọi `getMe` xác thực token + đếm số người đăng ký) — KHÔNG gửi tin tới subscriber để tránh spam |
| `/subs` | Quét ngay (`getUpdates`) & liệt kê người đăng ký theo từng bot đích (số người + tên + `chat_id`) |
| `/unsub <bot> <chat_id>` | Gỡ & **CHẶN VĨNH VIỄN** 1 người khỏi 1 bot (ghi `bot_blocklist`) — getUpdates KHÔNG bao giờ thêm lại dù họ nhắn bot. `<bot>` = tên nhãn hoặc bot_id; `<chat_id>` lấy từ `/subs` |
| `/resub <bot> <chat_id>` | Bỏ chặn (xoá khỏi `bot_blocklist`) — người đó /start lại bot sẽ được nhận tin trở lại |
| `/blocked` | Liệt kê người đang bị chặn theo từng bot đích (chat_id + thời điểm chặn) |

### Định dạng tin nhắn bot nhận diện (CHỈ đọc từ `SOURCE_BOT`)

**1. Tín hiệu BUY dạng text** (tin **bắt buộc chứa header `Deep Analysis`** — không phân biệt hoa thường; mỗi tín hiệu 1 dòng dạng `<số>. <COIN>/USDT [BUY]`, có thể kèm emoji đầu dòng). Bắt **MỌI** dòng trong tin, chỉ ghi nhận `[BUY]`, bỏ qua `[SELL]`:
```
🔍 Deep Analysis — 1 signals
🟢 1. BANANA/USDT [BUY]
```
→ Mỗi coin BUY ghi `RAW_SIGNAL` (cột `timeframe` để `text`), cộng dồn đếm tín hiệu rồi đi qua gác cổng như mục "Logic lọc kèo" (KHÔNG force_urgent → cần coin nhắc ≥ 2 lần/ngày mới chốt kèo). Tin **KHÔNG** có header `Deep Analysis` → bỏ qua hoàn toàn.

**2. Dòng tiền luân chuyển** (tin **bắt buộc chứa header `SMART MONEY ROTATION`** — không phân biệt hoa thường, và dùng mũi tên `→` U+2192). Bắt **MỌI** cặp `X → Y` trong tin (không chỉ cặp đầu):
```
SMART MONEY ROTATION
TON → NEAR
BTC → SOL
```
→ Mỗi cặp ghi 1 dòng vào bảng `money_flow`, coin đích (NEAR, SOL) được cộng đếm và đánh giá (`source="ROTATION:<coin_from>"`, **KHÔNG** force_urgent → chỉ chốt kèo khi coin đích gom đủ ≥ 2 lượt nhắc trong ngày + pass gác cổng). Tin có mũi tên nhưng **KHÔNG** có header `SMART MONEY ROTATION` → bỏ qua hoàn toàn. Kèo chốt từ luồng này broadcast với **nhãn riêng 2 dòng** (header + cặp `X → Y`), thay cho `KÈO VIP`/`KÈO THƯỜNG`:
```
⚡ SMART MONEY ROTATION
💰 SCRT → CFG
💯 Điểm: 60/100 (hạng 5 hôm nay)
📥 Entry: 0.086100 - SL: 0.077194 (-10.3%) - TP1: 0.099459 (+15.5%) | TP2: 0.112818 (+31.0%)
RSI: 53 | L/S: 0.75 | FR: 0.0050%
```

**3. Watchlist đột biến** (tin nhắn chứa cả chữ `Watchlist` và `Mới thêm`, coin nằm sau dấu `•` và trước dấu `—` hoặc `-`):
```
Watchlist Mới thêm:
• SOL — volume tăng đột biến
• AVAX - breakout
```
→ Ghi `RAW_URGENT` và **đánh giá NGAY** (force_urgent, bỏ qua điều kiện ≥ 2 lần nhắc). Kèo chốt từ Watchlist broadcast với **nhãn riêng `Watchlist`** (thay cho `KÈO VIP`/`KÈO THƯỜNG`), icon vẫn theo loại thật (🌟 VIP / ✅ thường), và **không** nâng nhãn lên `KÈO VIP` dù là TOP PICK:
```
✅ Watchlist: XPL
💯 Điểm: 60/100 (hạng 5 hôm nay)
📥 Entry: 0.086100 - SL: 0.077194 (-10.3%) - TP1: 0.099459 (+15.5%) | TP2: 0.112818 (+31.0%)
RSI: 53 | L/S: 0.75 | FR: 0.0050%
```

**3b. Cảnh báo nhanh Capital Convergence** (tin chứa `Capital Convergence`, dòng dạng `• ENJ — Capital Convergence: <lý do>`): NGOÀI luồng RAW_URGENT ở trên, mỗi coin còn đi qua `convergence_alert` — chạy TRƯỚC gác cổng để cảnh báo ngay lập tức:
- Soi ngay khung 1H + 4H (`BinanceRadar.analyze_convergence` — 2 call klines), KHÔNG qua gác cổng EMA và KHÔNG ghi bảng `signals` (tránh cộng lượt nhắc ảo).
- Điều kiện bắn: |biến động giá 24h| < 10% **HOẶC** giá còn nằm trong dải Bollinger MA99 (SMA99 ± 2σ) khung 1H — coin đã pump quá thì im lặng (chỉ log console). **VÀ** TP1 phải ≥ +10% so với entry (`tp1/entry - 1 ≥ 10%`) — TP1 quá hẹp thì chỉ log console, KHÔNG cảnh báo.
- Entry = giá đóng 1H mới nhất; TP1 = kháng cự (pivot high cửa sổ 3-3) 1H gần nhất phía trên, tối thiểu +1% (không có → +3%); TP2 = kháng cự 4H nằm trên TP1 (không có → +6%); SL = hỗ trợ (pivot low) 1H gần nhất phía dưới, tối thiểu −1%, hỗ trợ xa hơn −8% thì lùi về −5%.
- Format broadcast (mỗi bot đích tự gửi qua Bot API):
```
👀Capital Convergence
✅ENJ: Nhiều nguồn vốn cùng chảy về 1 coin
📥 Entry: xx - SL: xx (-xx%) - TP1: xx (+xx%) | TP2: xx (+xx%)
```

**3c. Cảnh báo nhanh MFI Breakout** (tin chứa `MFI Breakout`, dòng dạng `AI — MFI Breakout: <lý do>` — coin đứng đầu, **không cần** dấu `•`): xử lý **y hệt mục 3b** — đi qua cùng hàm `convergence_alert` (cùng `BinanceRadar.analyze_convergence`, cùng điều kiện bắn |biến động 24h| < 10% HOẶC trong dải BB MA99 1H **VÀ** TP1 ≥ +10%, KHÔNG qua gác cổng EMA, KHÔNG ghi bảng `signals`), **chỉ khác tiêu đề** dòng đầu. Bắt mọi cặp `<COIN> — MFI Breakout: ...` trong tin (regex chấp nhận em/en dash `—–`, gạch ngang `-`, có/không dấu `:`). Format broadcast:
```
👀 MFI Breakout kèm volume cao
✅AI: Dòng tiền đột biến
📥 Entry: xx - SL: xx (-xx%) - TP1: xx (+xx%) | TP2: xx (+xx%)
```

**3d. Hủy coin "đổi sang RS Divergence"** (tin chứa header `Cập nhật tín hiệu`, dòng dạng `ASTER: đổi sang RS Divergence`): parse TRƯỚC 3 luồng tức thời (Watchlist 3 / Capital Convergence 3b / MFI Breakout 3c) để gom tập `cancelled_coins`. Coin trong tập này bị **BỎ QUA hoàn toàn** ở cả 3 luồng (không soi nhanh, không ghi `RAW_URGENT`, không `check_and_evaluate`). Đồng thời **xóa `RAW_URGENT` đã ghi trong ngày** cho coin đó (kể cả từ tin trước đó) để không còn cộng lượt nhắc. Regex bắt coin đứng trước cụm `đổi sang RS Divergence`, ngăn cách bằng `:` (hoặc dash `—–-`); chỉ áp dụng khi tin có header `Cập nhật tín hiệu`. Chỉ hủy đúng cập nhật **RS Divergence** — các cập nhật khác trong cùng mục bị bỏ qua. Phạm vi: chỉ tác động tin hiện tại + RAW_URGENT trong DB; nếu tin SAU lại thêm coin đó như tín hiệu mới thì vẫn phân tích bình thường (không chặn vĩnh viễn).

**4. File Excel/CSV đính kèm**: **CHỈ xử lý file có TÊN chứa `signals_v4`** (không phân biệt hoa thường — đọc qua `message.file.name`); bot nguồn gửi nhiều Excel thì các file khác bị bỏ qua hoàn toàn (không tải về, chỉ log `📎 Bỏ qua file Excel...`). File hợp lệ cần có cột chứa chữ `SYMBOL` hoặc `COIN`, và cột điểm đúng tên `PRIORITY_SCORE`. Chỉ lấy dòng `signal = BUY` (qua cột chứa `SIGNAL`/`DIRECTION`; file không có cột này thì lấy hết) **và** điểm **≥ 70**; các dòng trùng coin được **khử trùng theo (coin, timeframe), giữ dòng `timestamp` mới nhất** (cùng 1 coin xuất hiện nhiều dòng do khác chỉ báo/nến → chỉ phát 1 tin/(coin,timeframe), tránh broadcast lặp). Mỗi dòng còn lại sau khử trùng được ghi `RAW_EXCEL` và **đánh giá NGAY**. File tạm `temp_data.xlsx` tự xóa sau xử lý.

**NGAY sau khi tải file, TRƯỚC khi xử lý tín hiệu từng coin** (`broadcast_market_status`): nếu file Excel có sheet tên `Buy Sell Bar` (cột `timeframe`/`BUY`/`SELL`, mỗi khung 1 dòng vd `1d`/`4h`) → phát 1 tin tổng quan thị trường tới các bot đích, đếm BUY/SELL theo khung **1D rồi 4H**. Chỉ áp dụng file Excel (CSV bỏ qua vì không có nhiều sheet); lỗi đọc sheet này được bọc try riêng, **KHÔNG** chặn việc xử lý tín hiệu chính. Phần tín hiệu vẫn dùng `pd.read_excel` mặc định **sheet đầu (`Signals`)**. Dựa trên **khung 4H**, thêm 1 câu kết luận: nếu `BUY ≥ 2×SELL` → `Buy đang áp đảo, yên tâm giữ hàng`; nếu `SELL ≥ 2×BUY` → `Sell đang áp đảo, cực kỳ cẩn thận` (giữa 2 ngưỡng, hoặc thiếu số liệu 4H → không thêm câu). Format:
```
⚠️ Market Status:
📊 1D: 🟢Buy/🔴Sell - 20/7
📊 4H: 🟢Buy/🔴Sell - 529/104
Buy đang áp đảo, yên tâm giữ hàng
```

Nếu file có thêm cột chứa chữ `TIMEFRAME` (hoặc tên đúng `TF`), giá trị timeframe của từng dòng (chuẩn hóa hoa, vd `4h`→`4H`, `1d`→`1D`) được truyền qua `check_and_evaluate(..., extra_tf=...)` và **chỉ** gắn vào cuối dòng stats của tin broadcast tức thời (`... | TF: 4H`) — **KHÔNG** lưu DB nên `/stats` và báo cáo định kỳ 07:00/16:00 không hiển thị TF. Các nguồn khác (text/watchlist/money-flow) không có dòng `TF:` (`extra_tf` mặc định `None`).

### Logic lọc kèo (Người Gác Cổng V6 — `check_and_evaluate`)

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

### Lịch tự động (timezone Asia/Ho_Chi_Minh, APScheduler)

| Giờ | Việc |
|---|---|
| 07:00 | Gửi "Bản tin điểm tâm VIP" vào Saved Messages + tất cả bot đích |
| 16:00 | Gửi báo cáo chiều vào Saved Messages + tất cả bot đích |
| 11:55 | Backup DB (Google Drive, fallback Desktop) |
| 23:55 | Backup DB (Google Drive, fallback Desktop) |
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
bot_state  (key TEXT PRIMARY KEY, value TEXT)   -- last_msg_id, last_report_sent, last_subs_poll, gu_offset_<bot_id>
bot_subscribers (bot_id TEXT, chat_id INTEGER, name TEXT, first_seen TEXT,
            PRIMARY KEY(bot_id, chat_id))        -- người đã /start mỗi bot đích (getUpdates thu thập) → đích relay
bot_blocklist (bot_id TEXT, chat_id INTEGER, ts TEXT,
            PRIMARY KEY(bot_id, chat_id))        -- /unsub → chặn vĩnh viễn, _upsert_subscriber bỏ qua người trong đây
```

Bảng `bot_state` (đọc/ghi qua `get_state`/`set_state`) gồm các key: `last_msg_id` (ID tin nhắn cuối của bot nguồn đã xử lý — mốc đọc bù), `last_report_sent` (ISO datetime lần gửi báo cáo định kỳ cuối — mốc gửi bù), `last_subs_poll` (lần quét getUpdates gần nhất), và `gu_offset_<bot_id>` (offset getUpdates đã xác nhận cho từng bot đích — để lần sau chỉ lấy update mới).

**Cơ chế subscriber bot đích** (`bot_subscribers`): mỗi bot đích là bot do người khác tạo và đưa token cho mình; tool gọi `getUpdates` định kỳ (job `interval` 2 phút + 1 lần lúc khởi động — `_poll_subscribers_worker`) cho từng token, gom mọi `chat.id` private nhắn bot → `_upsert_subscriber` lưu vào `bot_subscribers`. Khi broadcast, mỗi bot relay tin tới TẤT CẢ subscriber của nó; ai block/xoá bot (`sendMessage` trả `blocked`/`deactivated`/`chat not found`) bị `remove_subscriber` gỡ tự động.

`_upsert_subscriber` trả trạng thái `'new'`/`'exists'`/`'blocked'`/`'error'`. **Offset getUpdates (`gu_offset_<bot_id>`) CHỈ được nhảy khi không có update nào trả `'error'`** (ghi DB lỗi, vd SQLite lock) — nếu lỡ nhảy offset khi ghi lỗi thì update /start "đã đọc" sẽ không bao giờ trả lại → người đó mất sub vĩnh viễn. Gặp `'error'` thì worker giữ nguyên offset để poll sau đọc lại + in cảnh báo console. Người trong blocklist (`bot_blocklist`, do `/unsub`) trả `'blocked'` → bỏ qua hoàn toàn, KHÔNG bao giờ thêm lại dù /start (bỏ chặn bằng `/resub`).

**Giới hạn Telegram: getUpdates chỉ giữ update ~24h** → người /start từ lâu mà không nhắn lại sẽ KHÔNG bắt được; cần họ nhắn /start lại khi tool đang chạy. Mỗi token chỉ cho **1 nơi** đọc update → nếu bot đó đang đặt webhook hoặc có nơi khác đang getUpdates cùng token thì poll của tool lỗi (409/webhook, in `⚠️ Poll subscriber <tên>: ...` ra console mỗi 2 phút) và không đọc được /start của ai.

5 cột cuối của `signals` chỉ có giá trị với kèo chốt (`BUY_HOA_HAU%`); tín hiệu thô để NULL. DB cũ tự migrate bằng `ALTER TABLE` trong `init_db` (lỗi "duplicate column" được nuốt). `init_db` chỉ dựng schema (CREATE/ALTER) **1 lần/tiến trình** nhờ cờ module `_DB_READY` — gần như mọi hàm DB gọi `init_db()` đầu vào nên không thể chạy ALTER mỗi lần (gọi `init_db(force=True)` nếu cần dựng lại). `insert_db` nhận tham số `columns` để insert đúng cột — mọi insert vào `signals` PHẢI truyền `columns`.

Các giá trị `type` trong bảng `signals`:

| Type | Ý nghĩa |
|---|---|
| `RAW_SIGNAL` | Tín hiệu BUY thô từ text |
| `RAW_URGENT` | Coin từ Watchlist đột biến |
| `RAW_EXCEL` | Coin từ file Excel/CSV (score > 70) |
| `BUY_HOA_HAU` | Pass kỹ thuật EMA 4H/1D (cột `timeframe` chứa chuỗi stats: RSI, L/S, FR) |
| `BUY_HOA_HAU_VIP` | Pass kỹ thuật + đủ bonus vĩ mô |
| `XIT_KY_THUAT` | Bị loại vì cấu trúc giá yếu (dưới EMA25) |
| `XIT_TP_HEP` | Pass EMA nhưng TP1 (4H) < +10% → loại sớm, KHÔNG broadcast (chỉ đếm trong mục "kèo đã bỏ qua"; `timeframe` ghi `TP1+x.x%`) |

Báo cáo `/stats` chỉ thống kê dữ liệu **trong ngày hiện tại** (lọc `date LIKE 'YYYY-MM-DD%'`).

## Kiến trúc file (6 khối, theo comment trong code)

| Khối | Thành phần | Vai trò |
|---|---|---|
| 1. Cấu hình | `load_config` (đọc `config.txt`), `load_target_bots` (đọc token + nhãn từ `target_bots.txt`), `_parse_entity`, `client`, `_bot_api`, `_send_via_bot`, `broadcast_to_bots` | Nạp API_ID/API_HASH/SOURCE_BOT + TOKEN bot đích từ file ngoài, khởi tạo Telethon session `megazord_session` (nguồn vào) + gửi ra qua Bot API (mỗi bot relay tới subscriber của nó) |
| 2. Quant Engine | class `BinanceRadar` (`get_klines`, `calculate_ema`, `calculate_rsi`, `calculate_atr`, `build_trade_plan`, `find_pivot_levels`, `analyze_convergence`, `check_market_weather`, `spy_on_derivatives`, `analyze_coin`) | Gọi Binance API: klines, EMA, RSI, ATR, thời tiết BTC/ETH, phái sinh (L/S, FR, OI) + tính Entry/SL/TP1/TP2 khung 4H + soi nhanh 1H/4H (pivot kháng cự/hỗ trợ, Bollinger MA99) cho cảnh báo Capital Convergence / MFI Breakout |
| 3. Lưu trữ | `init_db` (kèm migrate), `insert_db`, `get_state`, `set_state`, `_upsert_subscriber`/`get_subscribers`/`remove_subscriber`/`_is_blocked`/`block_subscriber`/`unblock_subscriber`/`get_blocklist`, `_poll_subscribers_worker`/`poll_subscribers_job`, `get_backup_dir`, `backup_to_drive` | SQLite (5 bảng: signals, money_flow, bot_state, bot_subscribers, bot_blocklist) + thu thập/chặn subscriber bot đích qua getUpdates + trạng thái đọc bù/gửi bù + copy DB sang Google Drive (fallback Desktop khi ổ G: chưa mount) |
| 4. Báo cáo | `generate_report` | Tổng hợp dòng tiền, 🏆 top 1-2 kèo điểm cao nhất (kèm Entry/SL/TP), các kèo Hoa Hậu khác xếp theo điểm, kèo rác trong ngày |
| 5. Gác cổng | `fmt_price`, `compute_score`, `get_today_rank`, `format_trade_plan`, `check_and_evaluate`, `process_source_message`, `main_handler`, `command_handler` | Lọc kèo 3 bước (kỹ thuật → vĩ mô/phái sinh → chấm điểm & xếp hạng) + parse 4 định dạng (chỉ từ bot nguồn, dùng chung cho real-time & đọc bù) + lệnh `/stats`, `/backup`, `/test`, `/subs`, `/unsub`, `/resub`, `/blocked` |
| 6. Khởi chạy | `catch_up_source_messages`, `_last_due_report_time`, `catch_up_missed_report`, `auto_send_report`, `main` | Đọc bù tin lỡ + gửi bù báo cáo lúc khởi động, APScheduler cron jobs, vòng lặp chính |

## Lưu ý kỹ thuật khi sửa code

- **Userbot cho NGUỒN VÀO + Bot API cho ĐẦU RA (hybrid)**: tài khoản cá nhân (Telethon) chỉ dùng để NGHE `SOURCE_BOT` — `events.NewMessage(chats=SOURCE_BOT, incoming=True)` (muốn nghe thêm nhiều nguồn, đổi thành list `chats=[bot1, bot2]`). Khâu PHÁT ra ngoài KHÔNG dùng userbot mà gọi **Bot API** (`_bot_api`/`_send_via_bot` → `api.telegram.org/bot<TOKEN>/...`): mỗi bot đích relay report tới subscriber của chính nó (xem "Cơ chế subscriber bot đích" ở mục Database). Lý do: bot không thể nhắn cho bot khác, nên chỉ tài khoản cá nhân mới NGHE được bot nguồn; nhưng để tin xuất hiện DO bot đích đăng (tới đúng người dùng của bot đó) thì phải dùng token của chúng.
- **Retry mạng trong `_bot_api`** (áp cho MỌI tin gửi qua Bot API — broadcast kèo real-time, báo cáo 07:00/16:00 + gửi bù, Capital Convergence / MFI Breakout, Market Status từ Excel, và cả `getUpdates`): hàm tự thử lại **tối đa 2 lần (tổng 3 lần)** khi gặp lỗi MẠNG TẠM THỜI (timeout / connection / HTTP 5xx) với backoff **1s → 3s**; lỗi `429` rate limit thì chờ đúng `retry_after` Telegram trả (cap 30s) rồi thử lại; lỗi VĨNH VIỄN (`blocked` / `deactivated` / `chat not found` / 400) **trả ngay không retry** để `broadcast_to_bots` vẫn `remove_subscriber` đúng như cũ. Timeout = `(connect 5s, read `read_timeout`s)` — tham số `read_timeout` mặc định **10s** cho `sendMessage` (Telegram khỏe phản hồi <1s, cần nhanh). `time.sleep` trong retry an toàn vì khi gửi tin `_send_via_bot` chạy qua `asyncio.to_thread` — KHÔNG nghẽn event loop.
- **`getUpdates` dùng `read_timeout=30` + `limit=100`** (KHÁC `sendMessage` để 10s): lần poll ĐẦU của 1 bot (chưa lưu `gu_offset_<bot_id>`) phải tải TOÀN BỘ backlog update ~24h → payload có thể lớn, 10s không đủ sẽ timeout → offset không bao giờ lưu → poll lỗi lặp vô hạn (đã gặp với bot backlog lớn). 30s đủ để lần đầu về kịp, lưu offset; mỗi poll thành công ghi `offset=max_uid+1` rút dần **100 update/lần** (job 2 phút) đến khi sạch rồi về trạng thái nhanh/nhỏ. Nếu 1 bot vẫn timeout 30s liên tục → nghi bot đó đang đặt **webhook** (xung đột getUpdates) hoặc token hỏng, gõ `/test` để xác định. `getUpdates` (job 2 phút) gọi thẳng nên 1 lần poll lỗi mạng có thể tốn thêm tới ~30s×3+backoff khi mạng chậm (hiếm, không ảnh hưởng đường Telethon nghe bot nguồn).
- **Timestamp tin nhắn lấy theo giờ GỬI** (`message.date` đổi sang `VN_TZ`), không phải giờ xử lý — để tin đọc bù được ghi đúng ngày. Khi sửa logic thời gian, dùng `VN_TZ` (global), tránh `datetime.now()` trần.
- **Đọc bù có thể trùng 1 tin**: `last_msg_id` ghi sau khi xử lý xong; nếu tool chết GIỮA LÚC đang xử lý 1 tin, tin đó sẽ được xử lý lại khi khởi động (coin bị đếm 2 lần) — chấp nhận được, hiếm gặp.
- **Người nhận phải /start bot đích trước**: Bot API chỉ cho bot nhắn tới user đã từng bắt chuyện với nó. Tool KHÔNG tự biết ai đã /start — phải `getUpdates` gom `chat_id` rồi mới gửi được (xem "Cơ chế subscriber"). `broadcast_to_bots` lặp `TARGET_BOT_TOKENS` → với mỗi bot lấy `get_subscribers(bot_id)` rồi gọi `_send_via_bot` cho từng người trong `asyncio.to_thread` (không nghẽn event loop), giãn 0.05s/người; lỗi `blocked`/`deactivated`/`chat not found` → `remove_subscriber` gỡ người đó. Token là secret → chỉ in nhãn tên bot (`label`), KHÔNG bao giờ in token/`bot_id` đầy đủ ra log.
- **Lệnh /stats, /backup, /test, /subs** bắt qua handler riêng `events.NewMessage(outgoing=True)`, và chỉ chạy khi `event.chat_id == MY_ID` (= **Saved Messages**, chat với chính mình). `MY_ID` lấy 1 lần lúc khởi động qua `client.get_me()`. Gõ lệnh ở chat khác → bị bỏ qua.
- **Blocking trong async**: `check_and_evaluate` (đã chuyển sang `async def`) vẫn dùng `requests` đồng bộ bên trong → block event loop khi phân tích (mỗi coin tốn ~6-8 HTTP call). Mọi call Binance (`get_klines`, `spy_on_derivatives`) đã có `timeout=10` nên 1 kết nối treo bị chặn tối đa 10s/call thay vì đứng bot vô hạn — nhưng vẫn block event loop trong lúc chờ. Nếu tối ưu sâu hơn, cân nhắc `asyncio.to_thread` hoặc `aiohttp`.
- **Nuốt lỗi**: nhiều chỗ `except: pass` / trả giá trị mặc định (`spy_on_derivatives` lỗi trả `1.0, 0.0, 0.0` — L/S=1.0 có thể làm sai điều kiện VIP). Khi debug nên thêm log trước. `analyze_coin` (`except: return None`) gộp chung "coin chưa niêm yết Binance Spot (symbol USDT không tồn tại → `get_klines` trả `Invalid symbol`)" lẫn lỗi mạng tạm thời — `check_and_evaluate` gặp `tech=None` thì in `⚠️ Bỏ qua <coin>: không lấy được dữ liệu Binance Spot...` rồi return (KHÔNG ghi DB, KHÔNG broadcast). Đây là lý do coin từ Excel có thể in header `🚨 KÍCH HOẠT MẮT THẦN V6` nhưng không có phân tích/loại bỏ.
- **Binance API không cần key** (toàn endpoint public) nhưng có rate limit — tránh spam `analyze_coin`. Mọi `requests.get` tới Binance đều đặt `timeout=10` (BẮT BUỘC vì chạy đồng bộ trong event loop — không có timeout thì 1 kết nối treo sẽ đứng cả bot); lỗi timeout được các `try/except` của `analyze_coin`/`analyze_convergence`/`check_market_weather`/`spy_on_derivatives` nuốt → trả `None`/giá trị mặc định.
- **SQL dùng f-string cho ngày** trong `generate_report`/`check_and_evaluate` — chuỗi ngày do bot tự sinh nên không phải injection từ ngoài, nhưng giữ đúng format `YYYY-MM-DD HH:MM:SS` khi sửa.
- `numpy` KHÔNG còn được import trong code (đã gỡ vì không dùng trực tiếp) nhưng vẫn giữ trong `requirements.txt` vì pandas cần nó ngầm.
- Coin symbol tự động ghép `USDT` khi gọi Binance (`{coin}USDT`) — chỉ hỗ trợ cặp USDT.
- File config đọc bằng `encoding='utf-8-sig'` để chấp nhận cả file lưu từ Notepad (UTF-8 có BOM). ID số trong config tự chuyển sang `int` qua `_parse_entity` (Telethon yêu cầu ID là số nguyên).
- Không commit: `config.txt` (chứa API_HASH thật), `target_bots.txt` (chứa TOKEN bot — secret), `megazord_session.session`, `trading_memory.db`, `temp_data.xlsx` — `.gitignore` đã chặn sẵn các file này.
