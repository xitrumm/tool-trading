# CLAUDE.md

File này cung cấp ngữ cảnh cho Claude Code (claude.ai/code) khi làm việc với mã nguồn trong repo này.

> **Tài liệu chi tiết tách riêng** (đọc theo nhu cầu khi sửa đúng mảng đó — giữ file này gọn để luôn nạp được):
> - [docs/message-formats.md](docs/message-formats.md) — 4+ định dạng tin nhận diện & format broadcast (parse trong `process_source_message`, `convergence_alert`, `broadcast_market_status`).
> - [docs/scoring-gating.md](docs/scoring-gating.md) — logic gác cổng 3 bước, trọng số chấm điểm, Entry/SL/TP (`check_and_evaluate`, `compute_score`, `build_trade_plan`).
> - [docs/database.md](docs/database.md) — schema SQLite, cơ chế subscriber/getUpdates, lịch APScheduler, đọc bù/gửi bù khi khởi động.

## Tổng quan dự án

**Bot Trading "Siêu Megazord V6"** — bot lọc tín hiệu crypto chạy trên **tài khoản Telegram cá nhân** (userbot qua Telethon, KHÔNG dùng bot token). Luồng hoạt động:

1. **Nghe** tin nhắn đến từ MỘT bot nguồn duy nhất — cấu hình `SOURCE_BOT` (text + file Excel/CSV đính kèm).
2. **Bắt tín hiệu** coin theo 4 định dạng (xem [docs/message-formats.md](docs/message-formats.md)).
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

### Định dạng tin nhắn, logic lọc kèo & database

3 mảng chi tiết nhất đã tách ra docs riêng (đọc khi sửa đúng mảng đó):

- **Định dạng tin nhắn bot nhận diện** (4+ format text/rotation/watchlist/convergence/MFI/Excel + format broadcast tương ứng) → [docs/message-formats.md](docs/message-formats.md).
- **Logic lọc kèo (Người Gác Cổng V6), trọng số chấm điểm, Entry/SL/TP** → [docs/scoring-gating.md](docs/scoring-gating.md).
- **Database (schema + type signals), cơ chế subscriber, lịch tự động, đọc bù/gửi bù** → [docs/database.md](docs/database.md).

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

- **Userbot cho NGUỒN VÀO + Bot API cho ĐẦU RA (hybrid)**: tài khoản cá nhân (Telethon) chỉ dùng để NGHE `SOURCE_BOT` — `events.NewMessage(chats=SOURCE_BOT, incoming=True)` (muốn nghe thêm nhiều nguồn, đổi thành list `chats=[bot1, bot2]`). Khâu PHÁT ra ngoài KHÔNG dùng userbot mà gọi **Bot API** (`_bot_api`/`_send_via_bot` → `api.telegram.org/bot<TOKEN>/...`): mỗi bot đích relay report tới subscriber của chính nó (xem "Cơ chế subscriber bot đích" trong [docs/database.md](docs/database.md)). Lý do: bot không thể nhắn cho bot khác, nên chỉ tài khoản cá nhân mới NGHE được bot nguồn; nhưng để tin xuất hiện DO bot đích đăng (tới đúng người dùng của bot đó) thì phải dùng token của chúng.
- **Retry mạng trong `_bot_api`** (áp cho MỌI tin gửi qua Bot API — broadcast kèo real-time, báo cáo 07:00/16:00 + gửi bù, Capital Convergence / MFI Breakout, Market Status từ Excel, và cả `getUpdates`): hàm tự thử lại **tối đa 2 lần (tổng 3 lần)** khi gặp lỗi MẠNG TẠM THỜI (timeout / connection / HTTP 5xx) với backoff **1s → 3s**; lỗi `429` rate limit thì chờ đúng `retry_after` Telegram trả (cap 30s) rồi thử lại; lỗi VĨNH VIỄN (`blocked` / `deactivated` / `chat not found` / 400) **trả ngay không retry** để `broadcast_to_bots` vẫn `remove_subscriber` đúng như cũ. Timeout = `(connect 5s, read `read_timeout`s)` — tham số `read_timeout` mặc định **10s** cho `sendMessage` (Telegram khỏe phản hồi <1s, cần nhanh). `time.sleep` trong retry an toàn vì khi gửi tin `_send_via_bot` chạy qua `asyncio.to_thread` — KHÔNG nghẽn event loop.
- **`getUpdates` dùng `read_timeout=30` + `limit=100`** (KHÁC `sendMessage` để 10s): lần poll ĐẦU của 1 bot (chưa lưu `gu_offset_<bot_id>`) phải tải TOÀN BỘ backlog update ~24h → payload có thể lớn, 10s không đủ sẽ timeout → offset không bao giờ lưu → poll lỗi lặp vô hạn (đã gặp với bot backlog lớn). 30s đủ để lần đầu về kịp, lưu offset; mỗi poll thành công ghi `offset=max_uid+1` rút dần **100 update/lần** (job 2 phút) đến khi sạch rồi về trạng thái nhanh/nhỏ. Nếu 1 bot vẫn timeout 30s liên tục → nghi bot đó đang đặt **webhook** (xung đột getUpdates) hoặc token hỏng, gõ `/test` để xác định. `getUpdates` (job 2 phút) gọi thẳng nên 1 lần poll lỗi mạng có thể tốn thêm tới ~30s×3+backoff khi mạng chậm (hiếm, không ảnh hưởng đường Telethon nghe bot nguồn).
- **Timestamp tin nhắn lấy theo giờ GỬI** (`message.date` đổi sang `VN_TZ`), không phải giờ xử lý — để tin đọc bù được ghi đúng ngày. Khi sửa logic thời gian, dùng `VN_TZ` (global), tránh `datetime.now()` trần.
- **Đọc bù có thể trùng 1 tin**: `last_msg_id` ghi sau khi xử lý xong; nếu tool chết GIỮA LÚC đang xử lý 1 tin, tin đó sẽ được xử lý lại khi khởi động (coin bị đếm 2 lần) — chấp nhận được, hiếm gặp.
- **Người nhận phải /start bot đích trước**: Bot API chỉ cho bot nhắn tới user đã từng bắt chuyện với nó. Tool KHÔNG tự biết ai đã /start — phải `getUpdates` gom `chat_id` rồi mới gửi được (xem "Cơ chế subscriber" trong [docs/database.md](docs/database.md)). `broadcast_to_bots` lặp `TARGET_BOT_TOKENS` → với mỗi bot lấy `get_subscribers(bot_id)` rồi gọi `_send_via_bot` cho từng người trong `asyncio.to_thread` (không nghẽn event loop), giãn 0.05s/người; lỗi `blocked`/`deactivated`/`chat not found` → `remove_subscriber` gỡ người đó. Token là secret → chỉ in nhãn tên bot (`label`), KHÔNG bao giờ in token/`bot_id` đầy đủ ra log.
- **Lệnh /stats, /backup, /test, /subs** bắt qua handler riêng `events.NewMessage(outgoing=True)`, và chỉ chạy khi `event.chat_id == MY_ID` (= **Saved Messages**, chat với chính mình). `MY_ID` lấy 1 lần lúc khởi động qua `client.get_me()`. Gõ lệnh ở chat khác → bị bỏ qua.
- **Blocking trong async**: `check_and_evaluate` (đã chuyển sang `async def`) vẫn dùng `requests` đồng bộ bên trong → block event loop khi phân tích (mỗi coin tốn ~6-8 HTTP call). Mọi call Binance (`get_klines`, `spy_on_derivatives`) đã có `timeout=10` nên 1 kết nối treo bị chặn tối đa 10s/call thay vì đứng bot vô hạn — nhưng vẫn block event loop trong lúc chờ. Nếu tối ưu sâu hơn, cân nhắc `asyncio.to_thread` hoặc `aiohttp`.
- **Nuốt lỗi**: nhiều chỗ `except: pass` / trả giá trị mặc định (`spy_on_derivatives` lỗi trả `1.0, 0.0, 0.0` — L/S=1.0 có thể làm sai điều kiện VIP). Khi debug nên thêm log trước. `analyze_coin` (`except: return None`) gộp chung "coin chưa niêm yết Binance Spot (symbol USDT không tồn tại → `get_klines` trả `Invalid symbol`)" lẫn lỗi mạng tạm thời — `check_and_evaluate` gặp `tech=None` thì in `⚠️ Bỏ qua <coin>: không lấy được dữ liệu Binance Spot...` rồi return (KHÔNG ghi DB, KHÔNG broadcast). Đây là lý do coin từ Excel có thể in header `🚨 KÍCH HOẠT MẮT THẦN V6` nhưng không có phân tích/loại bỏ.
- **Binance API không cần key** (toàn endpoint public) nhưng có rate limit — tránh spam `analyze_coin`. Mọi `requests.get` tới Binance đều đặt `timeout=10` (BẮT BUỘC vì chạy đồng bộ trong event loop — không có timeout thì 1 kết nối treo sẽ đứng cả bot); lỗi timeout được các `try/except` của `analyze_coin`/`analyze_convergence`/`check_market_weather`/`spy_on_derivatives` nuốt → trả `None`/giá trị mặc định.
- **SQL dùng f-string cho ngày** trong `generate_report`/`check_and_evaluate` — chuỗi ngày do bot tự sinh nên không phải injection từ ngoài, nhưng giữ đúng format `YYYY-MM-DD HH:MM:SS` khi sửa.
- `numpy` KHÔNG còn được import trong code (đã gỡ vì không dùng trực tiếp) nhưng vẫn giữ trong `requirements.txt` vì pandas cần nó ngầm.
- Coin symbol tự động ghép `USDT` khi gọi Binance (`{coin}USDT`) — chỉ hỗ trợ cặp USDT.
- File config đọc bằng `encoding='utf-8-sig'` để chấp nhận cả file lưu từ Notepad (UTF-8 có BOM). ID số trong config tự chuyển sang `int` qua `_parse_entity` (Telethon yêu cầu ID là số nguyên).
- Không commit: `config.txt` (chứa API_HASH thật), `target_bots.txt` (chứa TOKEN bot — secret), `megazord_session.session`, `trading_memory.db`, `temp_data.xlsx` — `.gitignore` đã chặn sẵn các file này.
