# Database, lịch tự động & đọc bù khi khởi động

> Tài liệu chi tiết tách từ [CLAUDE.md](../CLAUDE.md). Đọc file này khi sửa schema SQLite, cơ chế subscriber (getUpdates), APScheduler, hoặc logic đọc bù / gửi bù lúc khởi động.

## Lịch tự động (timezone Asia/Ho_Chi_Minh, APScheduler)

| Giờ | Việc |
|---|---|
| 07:00 | Gửi "Bản tin điểm tâm VIP" vào Saved Messages + tất cả bot đích |
| 16:00 | Gửi báo cáo chiều vào Saved Messages + tất cả bot đích |
| 11:55 | Backup DB (Google Drive, fallback Desktop) |
| 23:55 | Backup DB (Google Drive, fallback Desktop) |
| Mỗi 2 phút (interval) | `poll_subscribers_job`: getUpdates từng bot đích, cập nhật `bot_subscribers` (bắt người mới /start) |

## Đọc bù & gửi bù khi khởi động (chống mất dữ liệu lúc tool tắt)

Mỗi lần khởi động, TRƯỚC khi vào vòng lặp chính, tool chạy 2 bước theo thứ tự:

1. **`catch_up_source_messages()` — đọc bù tin nhắn**: lấy `last_msg_id` (ID tin cuối đã xử lý, lưu trong bảng `bot_state`) rồi kéo mọi tin bot nguồn gửi SAU mốc đó qua `iter_messages(min_id=..., reverse=True)`, lọc bỏ tin do mình gõ (`if not m.out`), xử lý từng tin bằng đúng pipeline thường (`process_source_message`). Tin đọc bù dùng **giờ gửi gốc của tin** (đổi sang giờ VN) nên đếm số lần nhắc vẫn đúng ngày. Giới hạn an toàn: tối đa 300 tin mới nhất (lỡ nhiều hơn thì bỏ phần cũ, có log). Lần chạy đầu tiên (chưa có mốc) chỉ ghi mốc, KHÔNG cày lại lịch sử.
2. **`catch_up_missed_report()` — gửi bù báo cáo**: so `last_report_sent` (bảng `bot_state`) với mốc báo cáo 07:00/16:00 gần nhất đã qua (`_last_due_report_time`); nếu tool offline qua mốc đó → gửi ngay 1 báo cáo có header "⏰ BÁO CÁO GỬI BÙ" vào Saved Messages + mọi bot đích. Chạy SAU bước đọc bù nên báo cáo đã gồm các kèo vừa đọc bù.

`last_msg_id` được cập nhật sau MỖI tin xử lý xong (khối `finally` của `process_source_message`); `last_report_sent` cập nhật sau mỗi lần `auto_send_report` chạy (kể cả theo lịch cron).

## Database (`trading_memory.db` — SQLite, tự tạo khi chạy)

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
