# Định dạng tin nhắn bot nhận diện (CHỈ đọc từ `SOURCE_BOT`)

> Tài liệu chi tiết tách từ [CLAUDE.md](../CLAUDE.md). Đọc file này khi sửa logic parse tin nhắn / format broadcast trong `process_source_message`, `convergence_alert`, `broadcast_market_status`.

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
