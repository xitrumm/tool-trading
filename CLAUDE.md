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
7. **Phát kèo real-time**: kèo chốt (VIP/Thường) broadcast NGAY tới tất cả bot đích trong `TARGET_BOTS`, kèm điểm + hạng + Entry/Stoploss/TP1/TP2.
8. **Báo cáo & backup tự động**: báo cáo gửi vào Saved Messages + tất cả bot đích 2 lần/ngày, backup DB lên Google Drive 2 lần/ngày.
9. **Chống mất dữ liệu khi tool tắt**: lúc khởi động tự đọc bù tin nhắn bị lỡ của bot nguồn và gửi bù báo cáo nếu offline qua mốc 07:00/16:00 (trạng thái lưu trong bảng `bot_state`).

```
SOURCE_BOT (1 bot nguồn) → lọc 3 bước + Binance → TARGET_BOTS (n bot đích) + Saved Messages
```

## ⚠️ Trạng thái mã nguồn (QUAN TRỌNG)

- **File chạy chính thức: `bottrading.py`** — mọi chỉnh sửa code thực hiện trên file này.
- `bottrading.txt` là bản dán gốc (bị lặp 2 lần cùng một nội dung), chỉ giữ để tham khảo — KHÔNG sửa/chạy file này, có thể xóa khi không cần.
- Cấu hình KHÔNG nằm trong code mà đọc từ 2 file ngoài (cùng thư mục với `bottrading.py`):
  - `config.txt` — `API_ID`, `API_HASH` (lấy từ https://my.telegram.org) và `SOURCE_BOT` (bot nguồn), dạng `KEY=VALUE`. **Chứa secret thật → đã gitignore.**
  - `target_bots.txt` — danh sách bot đích, mỗi dòng 1 bot (@username hoặc ID số), dòng `#` là comment.
- Cả 2 file đang chứa giá trị **placeholder** — phải điền giá trị thật trước khi chạy. Thiếu file / thiếu giá trị → bot in lỗi tiếng Việt rõ ràng và thoát ngay lúc khởi động (`SystemExit` trong `load_config` / `load_target_bots`).
- Nơi backup DB chọn tự động qua `get_backup_dir()`: ưu tiên `G:\My Drive\Trading_Bot` (Google Drive for desktop mount ổ G:), nếu ổ G: chưa mount thì fallback sang `Desktop\Trading_Bot` (có xử lý cả trường hợp Desktop bị OneDrive chuyển hướng).

## Cài đặt & Chạy

```powershell
# 1. Cài dependencies (Python 3.8+)
pip install -r requirements.txt

# 2. Mở config.txt — điền API_ID, API_HASH thật (my.telegram.org → API development tools)
#    và SOURCE_BOT (@username hoặc ID số của bot nguồn cần đọc)

# 3. Mở target_bots.txt — mỗi dòng 1 bot đích sẽ nhận kết quả
#    Nhớ bấm /start với TỪNG bot đích trước!

# 4. Chạy bot
python bottrading.py
```

**Lần chạy đầu tiên**: Telethon sẽ hỏi số điện thoại → mã OTP gửi qua Telegram → mật khẩu 2FA (nếu có). Sau đó tạo file `megazord_session.session` — **giữ bí mật file này** (ai có nó là đăng nhập được tài khoản), không commit lên git.

Bot chạy đến khi mất kết nối / Ctrl+C (`run_until_disconnected`). Khi khởi động in dòng `🚀 SIÊU MEGAZORD V6 ĐÃ LÊN NÒNG!` và backup DB ngay 1 lần.

### Kiểm tra tool hoạt động (lần đầu chạy)

1. **Console**: phải in `🚀 SIÊU MEGAZORD V6 ĐÃ LÊN NÒNG!` + dòng `📡 Nguồn vào: ... | 📤 Bot đích (...)` → đăng nhập & nạp config thành công.
2. **Gõ `/stats` trong Saved Messages**: tool trả lời ngay (kể cả khi chưa có dữ liệu) → chứng tỏ đang nghe và gửi được.
3. **Gõ `/test`**: tự kiểm tra 3 đường — Binance Spot/Futures, SQLite, gửi thử tới TỪNG bot đích (báo ✅/❌ từng mục). Mở chat từng bot đích xác nhận có tin 🧪.
4. **Test luồng thật**: làm bot nguồn gửi tin dạng Watchlist (được đánh giá NGAY, không cần đủ 2 lần nhắc) → console in `🚨 KÍCH HOẠT MẮT THẦN V6` + bot đích nhận kèo nếu pass kỹ thuật. Lưu ý: tin phải do CHÍNH bot nguồn gửi đến — tự gõ vào chat đó không kích hoạt (filter `incoming=True`).

## Cách sử dụng chi tiết

### Lệnh điều khiển (chỉ nhận tin do CHÍNH tài khoản đang chạy bot gõ ra — filter `outgoing=True`)

Gõ vào bất kỳ chat nào từ tài khoản của bạn (tiện nhất là **Saved Messages**):

| Lệnh | Tác dụng |
|---|---|
| `/stats` | Trả về báo cáo dòng tiền tổng hợp trong ngày (top ngành hút tiền, 🏆 top 1-2 kèo đáng giá nhất kèm Entry/SL/TP, các kèo Hoa Hậu khác xếp theo điểm giảm dần, kèo rác đã chặn) |
| `/backup` | Copy `trading_memory.db` lên Google Drive ngay (ổ G: chưa mount → lưu `Desktop\Trading_Bot`); trả lời kèm đường dẫn đã lưu |
| `/test` | Tự kiểm tra: Binance Spot/Futures, SQLite, gửi tin thử tới TỪNG bot đích — trả về ✅/❌ từng mục |

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
Kèo chốt (cả VIP lẫn Thường) → broadcast NGAY tới mọi bot trong TARGET_BOTS,
tin nhắn kèm: 💯 điểm + hạng, 📥 Entry, 🛑 Stoploss, 🎯 TP1/TP2 (kèm %),
TOP PICK có header 🏆🏆🏆 nổi bật. (Kèo XIT_KY_THUAT chỉ ghi DB, KHÔNG gửi đi)
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
bot_state  (key TEXT PRIMARY KEY, value TEXT)   -- trạng thái: last_msg_id, last_report_sent
```

Bảng `bot_state` (đọc/ghi qua `get_state`/`set_state`) hiện có 2 key: `last_msg_id` (ID tin nhắn cuối của bot nguồn đã xử lý — mốc đọc bù) và `last_report_sent` (ISO datetime lần gửi báo cáo định kỳ cuối — mốc gửi bù).

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

Báo cáo `/stats` chỉ thống kê dữ liệu **trong ngày hiện tại** (lọc `date LIKE 'YYYY-MM-DD%'`).

## Kiến trúc file (6 khối, theo comment trong code)

| Khối | Thành phần | Vai trò |
|---|---|---|
| 1. Cấu hình | `load_config` (đọc `config.txt`), `load_target_bots` (đọc `target_bots.txt`), `_parse_entity`, `client`, `broadcast_to_bots` | Nạp API_ID/API_HASH/SOURCE_BOT/TARGET_BOTS từ file ngoài, khởi tạo Telethon session `megazord_session`, định tuyến nguồn vào/đầu ra |
| 2. Quant Engine | class `BinanceRadar` (`get_klines`, `calculate_ema`, `calculate_rsi`, `calculate_atr`, `build_trade_plan`, `check_market_weather`, `spy_on_derivatives`, `analyze_coin`) | Gọi Binance API: klines, EMA, RSI, ATR, thời tiết BTC/ETH, phái sinh (L/S, FR, OI) + tính Entry/SL/TP1/TP2 khung 4H |
| 3. Lưu trữ | `init_db` (kèm migrate), `insert_db`, `get_state`, `set_state`, `get_backup_dir`, `backup_to_drive` | SQLite (3 bảng) + trạng thái đọc bù/gửi bù + copy DB sang Google Drive (fallback Desktop khi ổ G: chưa mount) |
| 4. Báo cáo | `generate_report` | Tổng hợp dòng tiền, 🏆 top 1-2 kèo điểm cao nhất (kèm Entry/SL/TP), các kèo Hoa Hậu khác xếp theo điểm, kèo rác trong ngày |
| 5. Gác cổng | `fmt_price`, `compute_score`, `get_today_rank`, `format_trade_plan`, `check_and_evaluate`, `process_source_message`, `main_handler`, `command_handler` | Lọc kèo 3 bước (kỹ thuật → vĩ mô/phái sinh → chấm điểm & xếp hạng) + parse 4 định dạng (chỉ từ bot nguồn, dùng chung cho real-time & đọc bù) + lệnh `/stats`, `/backup`, `/test` |
| 6. Khởi chạy | `catch_up_source_messages`, `_last_due_report_time`, `catch_up_missed_report`, `auto_send_report`, `main` | Đọc bù tin lỡ + gửi bù báo cáo lúc khởi động, APScheduler cron jobs, vòng lặp chính |

## Lưu ý kỹ thuật khi sửa code

- **Userbot, không phải bot API**: đăng nhập bằng tài khoản cá nhân. Nguồn vào lọc bằng `events.NewMessage(chats=SOURCE_BOT, incoming=True)` — muốn nghe thêm nhiều nguồn, đổi thành list `chats=[bot1, bot2]`.
- **Timestamp tin nhắn lấy theo giờ GỬI** (`message.date` đổi sang `VN_TZ`), không phải giờ xử lý — để tin đọc bù được ghi đúng ngày. Khi sửa logic thời gian, dùng `VN_TZ` (global), tránh `datetime.now()` trần.
- **Đọc bù có thể trùng 1 tin**: `last_msg_id` ghi sau khi xử lý xong; nếu tool chết GIỮA LÚC đang xử lý 1 tin, tin đó sẽ được xử lý lại khi khởi động (coin bị đếm 2 lần) — chấp nhận được, hiếm gặp.
- **Bot đích phải được /start trước**: Telegram chặn user nhắn cho bot chưa từng bắt chuyện. `broadcast_to_bots` giãn 1 giây giữa các lần gửi để tránh FloodWait; bot nào gửi lỗi chỉ in log, không làm dừng vòng gửi.
- **Lệnh /stats, /backup** bắt qua handler riêng `events.NewMessage(outgoing=True)` — chỉ tin nhắn do CHÍNH bạn gõ, ở bất kỳ chat nào.
- **Blocking trong async**: `check_and_evaluate` (đã chuyển sang `async def`) vẫn dùng `requests` đồng bộ bên trong → block event loop khi phân tích (mỗi coin tốn ~6-8 HTTP call). Nếu tối ưu, cân nhắc `asyncio.to_thread` hoặc `aiohttp`.
- **Nuốt lỗi**: nhiều chỗ `except: pass` / trả giá trị mặc định (`spy_on_derivatives` lỗi trả `1.0, 0.0, 0.0` — L/S=1.0 có thể làm sai điều kiện VIP). Khi debug nên thêm log trước.
- **Binance API không cần key** (toàn endpoint public) nhưng có rate limit — tránh spam `analyze_coin`.
- **SQL dùng f-string cho ngày** trong `generate_report`/`check_and_evaluate` — chuỗi ngày do bot tự sinh nên không phải injection từ ngoài, nhưng giữ đúng format `YYYY-MM-DD HH:MM:SS` khi sửa.
- `numpy` được import nhưng không dùng trực tiếp (pandas cần nó ngầm).
- Coin symbol tự động ghép `USDT` khi gọi Binance (`{coin}USDT`) — chỉ hỗ trợ cặp USDT.
- File config đọc bằng `encoding='utf-8-sig'` để chấp nhận cả file lưu từ Notepad (UTF-8 có BOM). ID số trong config tự chuyển sang `int` qua `_parse_entity` (Telethon yêu cầu ID là số nguyên).
- Không commit: `config.txt` (chứa API_HASH thật), `megazord_session.session`, `trading_memory.db`, `temp_data.xlsx` — `.gitignore` đã chặn sẵn các file này.
