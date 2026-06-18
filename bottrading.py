import sqlite3
import re
import datetime
import time
import requests
import pandas as pd
import os
import shutil
import sys
import asyncio
from telethon import TelegramClient, events
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import pytz

VN_TZ = pytz.timezone('Asia/Ho_Chi_Minh')  # mọi mốc thời gian của tool tính theo giờ Việt Nam

# ==========================================
# 0. GHI LOG CMD RA FILE (tee stdout/stderr)
# ==========================================
# Ghi lại MỌI thứ in ra console (print + traceback lỗi) vào file để tiện debug,
# nhưng VẪN hiện trên cmd như cũ. File: logs/bottrading_YYYY-MM-DD.log (cùng thư mục tool).
class _Tee:
    """Ghi đồng thời ra console gốc và file log, kèm timestamp đầu mỗi dòng."""
    def __init__(self, stream, logfile):
        self.stream = stream          # console gốc (stdout/stderr)
        self.logfile = logfile        # handle file log (mở chung cho cả 2 luồng)
        self._at_line_start = True    # chỉ chèn timestamp ở đầu dòng mới

    def write(self, text):
        self.stream.write(text)       # vẫn in ra cmd như cũ
        try:
            for ch in text:
                if self._at_line_start and ch != '\n':
                    self.logfile.write('[' + datetime.datetime.now(VN_TZ).strftime('%Y-%m-%d %H:%M:%S') + '] ')
                    self._at_line_start = False
                self.logfile.write(ch)
                if ch == '\n':
                    self._at_line_start = True
            self.logfile.flush()      # flush ngay để không mất log khi tool bị kill
        except Exception:
            pass                      # lỗi ghi log không được làm sập tool

    def flush(self):
        self.stream.flush()
        try:
            self.logfile.flush()
        except Exception:
            pass

def _setup_logging():
    """Bật tee stdout/stderr -> file log theo ngày. Gọi sớm nhất có thể."""
    try:
        log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, 'bottrading_' + datetime.datetime.now(VN_TZ).strftime('%Y-%m-%d') + '.log')
        # encoding utf-8 để giữ emoji/tiếng Việt; mở append để gộp nhiều lần chạy trong ngày
        f = open(log_path, 'a', encoding='utf-8')
        f.write('\n===== KHỞI ĐỘNG ' + datetime.datetime.now(VN_TZ).strftime('%Y-%m-%d %H:%M:%S') + ' =====\n')
        f.flush()
        sys.stdout = _Tee(sys.stdout, f)
        sys.stderr = _Tee(sys.stderr, f)
    except Exception as e:
        # không ghi được log thì vẫn chạy bot bình thường
        print('⚠️ Không bật được ghi log ra file:', e)

_setup_logging()

# ==========================================
# 1. CẤU HÌNH BỘ NÃO
# ==========================================
# Toàn bộ cấu hình đọc từ 2 file ngoài (đặt cùng thư mục với bottrading.py):
#   - config.txt      : API_ID, API_HASH, SOURCE_BOT (dạng KEY=VALUE)
#   - target_bots.txt : danh sách bot đích, mỗi dòng 1 bot
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, 'config.txt')
TARGET_BOTS_FILE = os.path.join(BASE_DIR, 'target_bots.txt')

def _parse_entity(value):
    """@username giữ nguyên chuỗi, ID số chuyển sang int (Telethon yêu cầu)"""
    value = value.strip()
    return int(value) if value.lstrip('-').isdigit() else value

def load_config():
    """Đọc config.txt dạng KEY=VALUE, bỏ qua dòng trống và dòng bắt đầu bằng #"""
    if not os.path.exists(CONFIG_FILE):
        raise SystemExit(f"❌ Không tìm thấy {CONFIG_FILE} — tạo file với 3 dòng: API_ID=..., API_HASH=..., SOURCE_BOT=...")
    cfg = {}
    with open(CONFIG_FILE, 'r', encoding='utf-8-sig') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line: continue
            key, _, value = line.partition('=')
            cfg[key.strip().upper()] = value.strip()
    missing = [k for k in ('API_ID', 'API_HASH', 'SOURCE_BOT') if not cfg.get(k)]
    if missing:
        raise SystemExit(f"❌ {CONFIG_FILE} thiếu giá trị: {', '.join(missing)}")
    if not cfg['API_ID'].isdigit():
        raise SystemExit(f"❌ API_ID trong {CONFIG_FILE} phải là dãy số (đang là: {cfg['API_ID']})")
    return cfg

def load_target_bots():
    """Đọc target_bots.txt — mỗi dòng 1 TOKEN bot đích (dạng 123456789:ABC... từ BotFather),
    kèm nhãn tên tùy chọn sau dấu # để dễ nhớ. Trả list (token, label).
    Token sai format bị bỏ qua (in cảnh báo, KHÔNG in token vì là secret)."""
    if not os.path.exists(TARGET_BOTS_FILE):
        raise SystemExit(f"❌ Không tìm thấy {TARGET_BOTS_FILE} — tạo file, mỗi dòng 1 token bot đích (lấy từ @BotFather)")
    bots = []
    with open(TARGET_BOTS_FILE, 'r', encoding='utf-8-sig') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            # Cho phép ghi chú tên bot sau token để dễ nhớ:
            #   8913020297:ABC... #xitrumm   HOẶC   8913020297:ABC... xitrumm
            # → token là field đầu (không chứa khoảng trắng); nhãn lấy sau dấu #
            #   (không có # thì lấy phần sau khoảng trắng; không có gì thì dùng id bot).
            before, _, after = line.partition('#')
            parts = before.split()
            token = parts[0] if parts else ''
            if not re.match(r'^\d+:.+$', token):
                print(f"   ⚠️ Bỏ qua 1 dòng trong {os.path.basename(TARGET_BOTS_FILE)}: sai format token (cần dạng 123456789:ABC...)")
                continue
            label = after.strip() or (' '.join(parts[1:]) if len(parts) > 1 else '') or token.split(':', 1)[0]
            bots.append((token, label))
    if not bots:
        raise SystemExit(f"❌ {TARGET_BOTS_FILE} không có token hợp lệ — thêm ít nhất 1 token bot (dạng 123456789:ABC... từ @BotFather)")
    return bots

_cfg = load_config()
API_ID = int(_cfg['API_ID'])                    # Dãy số ID từ my.telegram.org
API_HASH = _cfg['API_HASH']                     # Chuỗi Hash từ my.telegram.org
SOURCE_BOT = _parse_entity(_cfg['SOURCE_BOT'])  # Bot nguồn: chỉ đọc tin nhắn từ bot này
TARGET_BOT_TOKENS = load_target_bots()          # Token các bot đích: mỗi bot relay report tới subscriber của nó
MY_ID = None                                    # user-id chính chủ — gán lúc khởi động; lệnh chỉ nhận trong Saved Messages

client = TelegramClient('megazord_session', API_ID, API_HASH)

def _bot_api(token, method, params=None, read_timeout=10):
    """Gọi 1 method Bot API (sendMessage/getMe/getUpdates...), trả dict JSON.
    KHÔNG raise — lỗi mạng trả {'ok': False, 'description': ...}.

    Tự RETRY tối đa 2 lần (tổng 3 lần thử) khi lỗi MẠNG TẠM THỜI (timeout/connection/5xx)
    với backoff 1s → 3s. KHÔNG retry lỗi vĩnh viễn (blocked/deactivated/chat not found...).
    Lỗi 429 (rate limit) thì chờ đúng `retry_after` Telegram trả về rồi thử lại.
    timeout=(connect 5s, read `read_timeout`s) — sendMessage để 10s (cần nhanh); getUpdates
    truyền read_timeout dài hơn (30s) vì payload backlog có thể lớn, poll nền không gấp."""
    last = {"ok": False, "description": "lỗi không xác định"}
    backoffs = [1, 3]   # chờ trước retry lần 1, lần 2
    for attempt in range(3):
        try:
            r = requests.post(f"https://api.telegram.org/bot{token}/{method}",
                              json=params or {}, timeout=(5, read_timeout))
            data = r.json()
            # 429 rate limit → chờ đúng retry_after rồi thử lại (không tính vào backoff thường)
            if (not data.get('ok')) and r.status_code == 429:
                wait = (data.get('parameters') or {}).get('retry_after', 1)
                if attempt < 2:
                    time.sleep(min(wait, 30))
                    last = data
                    continue
            # 5xx (lỗi tạm phía Telegram) → coi như lỗi mạng, retry
            if (not data.get('ok')) and r.status_code >= 500 and attempt < 2:
                last = data
                time.sleep(backoffs[attempt])
                continue
            return data   # thành công, hoặc lỗi vĩnh viễn (blocked/chat not found/400...) → trả ngay
        except Exception as e:
            last = {"ok": False, "description": f"lỗi kết nối: {e}"}
            if attempt < 2:
                time.sleep(backoffs[attempt])
    return last

def _send_via_bot(token, chat_id, text):
    """CHÍNH bot (token) tự gửi 1 tin tới chat_id. Plain text (không parse_mode) —
    tin kèo/report chỉ chứa emoji, không markdown. Trả (ok: bool, description: str)."""
    data = _bot_api(token, "sendMessage", {"chat_id": chat_id, "text": text})
    return bool(data.get('ok')), str(data.get('description', '') or '')

async def broadcast_to_bots(message, tag=None):
    """Mỗi bot đích RELAY tin tới TẤT CẢ người đã đăng ký bot đó (đã /start hoặc nhắn tin —
    chat_id thu thập qua getUpdates, lưu bảng bot_subscribers). Người block/xoá bot bị gỡ tự động.
    Chạy gửi trong thread riêng (asyncio.to_thread) để không nghẽn event loop Telegram.
    `tag` = nhãn nhận diện tin (coin/loại) in kèm log — không truyền thì lấy dòng đầu của tin;
    nhờ vậy log gửi không bị quy nhầm cho coin vừa bị loại khi nhiều task async chen nhau."""
    tag = (tag or (message.splitlines()[0] if message else ''))[:40]
    now = datetime.datetime.now(VN_TZ).strftime('%Y-%m-%d %H:%M:%S')
    print(f"\n[{now}]    📨 Bắt đầu phát tin: [{tag}]")
    total_sent = 0
    for token, label in TARGET_BOT_TOKENS:
        bot_id = token.split(':', 1)[0]
        subs = get_subscribers(bot_id)
        if not subs:
            print(f"   ⚠️ Bot {label}: chưa có người đăng ký — nhờ người tạo bot nhắn /start lại khi tool đang chạy (gõ /subs để quét).")
            continue
        sent = 0
        for chat_id, name in subs:
            try:
                ok, desc = await asyncio.to_thread(_send_via_bot, token, chat_id, message)
                if ok:
                    sent += 1
                    total_sent += 1
                elif any(k in desc.lower() for k in ('blocked', 'deactivated', 'chat not found')):
                    remove_subscriber(bot_id, chat_id)   # người đã block/xoá bot → ngừng gửi
                    print(f"   🧹 Bot {label}: gỡ {name} ({desc})")
                else:
                    print(f"   ⚠️ Bot {label} → {name} lỗi: {desc}")
                await asyncio.sleep(0.05)
            except Exception as e:
                print(f"   ⚠️ Bot {label} → {name} lỗi: {e}")
        print(f"   📤 [{tag}] Bot {label}: gửi {sent}/{len(subs)} người")
    print(f"   📤 [{tag}] Tổng đã phát: {total_sent} tin")

# ==========================================
# 2. KHỐI VỆ TINH BINANCE (QUANT ENGINE V6)
# ==========================================
class BinanceRadar:
    def __init__(self):
        self.base_url = "https://api.binance.com/api/v3"
        self.fapi_url = "https://fapi.binance.com/fapi/v1"
        self.data_url = "https://fapi.binance.com/futures/data"

    def get_klines(self, symbol, interval, limit=100):
        url = f"{self.base_url}/klines?symbol={symbol}&interval={interval}&limit={limit}"
        # timeout BẮT BUỘC: các call này chạy ĐỒNG BỘ trong event loop — Binance treo 1 kết nối
        # mà không có timeout sẽ làm ĐỨNG toàn bộ bot (mất nghe nguồn + scheduler + heartbeat).
        res = requests.get(url, timeout=10).json()
        df = pd.DataFrame(res, columns=['time', 'open', 'high', 'low', 'close', 'volume', 'close_time', 'qav', 'num_trades', 'tbbav', 'tbqav', 'ignore'])
        for col in ('open', 'high', 'low', 'close'):
            df[col] = df[col].astype(float)
        return df

    def calculate_ema(self, df, period):
        return df['close'].ewm(span=period, adjust=False).mean().iloc[-1]

    def calculate_rsi(self, df, periods=14):
        delta = df['close'].diff()
        gain = delta.where(delta > 0, 0)
        loss = -delta.where(delta < 0, 0)
        avg_gain = gain.ewm(alpha=1/periods, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1/periods, adjust=False).mean()
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return rsi.iloc[-1]

    def calculate_atr(self, df, period=14):
        """Average True Range — đo biên độ dao động để đặt Stoploss/TP theo nhịp thị trường"""
        prev_close = df['close'].shift(1)
        tr = pd.concat([
            df['high'] - df['low'],
            (df['high'] - prev_close).abs(),
            (df['low'] - prev_close).abs()
        ], axis=1).max(axis=1)
        return tr.ewm(alpha=1/period, adjust=False).mean().iloc[-1]

    def build_trade_plan(self, df_4h, ema25_4h):
        """Tính Entry / Stoploss / TP1 / TP2 từ khung 4H.
        SL đặt dưới hỗ trợ (swing low 20 nến hoặc EMA25 4H) trừ đệm 0.5 ATR,
        chặn tối đa -8% so với entry. TP theo R:R 1.5 và 3.0."""
        entry = df_4h['close'].iloc[-1]
        atr = self.calculate_atr(df_4h)
        swing_low = df_4h['low'].iloc[-20:].min()
        sl = min(swing_low, ema25_4h) - 0.5 * atr
        if sl <= 0 or (entry - sl) / entry > 0.08:
            sl = entry - 2 * atr
        if sl >= entry:  # ATR bất thường (coin mới list, dữ liệu lỗi)
            sl = entry * 0.95
        risk = entry - sl
        return {'entry': entry, 'sl': sl, 'tp1': entry + 1.5 * risk, 'tp2': entry + 3 * risk}

    def find_pivot_levels(self, df, left=3, right=3):
        """Liệt kê các mốc swing high / swing low (pivot): nến cao/thấp nhất trong
        cửa sổ left+right nến quanh nó. Pivot high = kháng cự, pivot low = hỗ trợ."""
        pivot_highs, pivot_lows = [], []
        highs, lows = df['high'], df['low']
        for i in range(left, len(df) - right):
            if highs.iloc[i] >= highs.iloc[i - left:i + right + 1].max():
                pivot_highs.append(float(highs.iloc[i]))
            if lows.iloc[i] <= lows.iloc[i - left:i + right + 1].min():
                pivot_lows.append(float(lows.iloc[i]))
        return pivot_highs, pivot_lows

    def analyze_convergence(self, symbol):
        """Soi nhanh khung 1H + 4H cho tin Capital Convergence (KHÔNG qua gác cổng EMA).
        Trả dict: entry = giá đóng 1H mới nhất, TP1 = kháng cự 1H gần nhất phía trên,
        TP2 = kháng cự 4H nằm trên TP1, SL = hỗ trợ 1H gần nhất phía dưới (kẹp -8%),
        change_24h = % biến động giá 24h, in_bb = giá còn nằm trong dải Bollinger
        MA99 (SMA99 ± 2σ) khung 1H hay không. Lỗi/thiếu dữ liệu → None."""
        try:
            df_1h = self.get_klines(symbol, "1h", 200)
            df_4h = self.get_klines(symbol, "4h", 180)
            entry = float(df_1h['close'].iloc[-1])

            # Biến động 24h: so với close 24 nến 1H trước (coin mới list thì so nến đầu)
            base = float(df_1h['close'].iloc[-25]) if len(df_1h) >= 25 else float(df_1h['close'].iloc[0])
            change_24h = (entry / base - 1) * 100

            ma99 = df_1h['close'].rolling(99).mean().iloc[-1]
            std99 = df_1h['close'].rolling(99).std().iloc[-1]
            in_bb = (not pd.isna(ma99)) and (not pd.isna(std99)) and \
                    (ma99 - 2 * std99) <= entry <= (ma99 + 2 * std99)

            res_1h, sup_1h = self.find_pivot_levels(df_1h)
            res_4h, _ = self.find_pivot_levels(df_4h)
            # TP1: kháng cự 1H gần nhất, tối thiểu +1% cho đáng vào lệnh (không có → +3%)
            above_1h = [p for p in res_1h if p > entry * 1.01]
            tp1 = min(above_1h) if above_1h else entry * 1.03
            # TP2: kháng cự 4H gần nhất nằm TRÊN TP1 (không có → +6% hoặc nhỉnh hơn TP1)
            above_4h = [p for p in res_4h if p > tp1 * 1.01]
            tp2 = min(above_4h) if above_4h else max(entry * 1.06, tp1 * 1.02)
            # SL: hỗ trợ 1H gần nhất, tối thiểu -1%; hỗ trợ xa hơn -8% thì lùi về -5%
            below_1h = [p for p in sup_1h if p < entry * 0.99]
            sl = max(below_1h) if below_1h else entry * 0.95
            if sl < entry * 0.92: sl = entry * 0.95

            return {'entry': entry, 'sl': sl, 'tp1': tp1, 'tp2': tp2,
                    'change_24h': change_24h, 'in_bb': in_bb}
        except Exception:
            return None

    def check_market_weather(self):
        """Kiểm tra cả 2 anh cả: BTC và ETH"""
        try:
            btc_df = self.get_klines("BTCUSDT", "1d", 30)
            eth_df = self.get_klines("ETHUSDT", "1d", 30)

            btc_ema25, btc_price = self.calculate_ema(btc_df, 25), btc_df['close'].iloc[-1]
            eth_ema25, eth_price = self.calculate_ema(eth_df, 25), eth_df['close'].iloc[-1]

            if btc_price > btc_ema25 and eth_price > eth_ema25:
                return "NẮNG ĐẸP (BTC+ETH Đều Xanh)"
            elif btc_price < btc_ema25 and eth_price < eth_ema25:
                return "BÃO TỐ (BTC+ETH Đều Gãy)"
            else:
                return "BIẾN ĐỘNG (1 Xanh 1 Đỏ)"
        except: return "LỖI KẾT NỐI"

    def spy_on_derivatives(self, symbol):
        """Quét 3 thông số Phái sinh: L/S Ratio, Funding Rate, Open Interest"""
        try:
            # L/S Ratio
            url_ls = f"{self.data_url}/topLongShortAccountRatio?symbol={symbol}&period=1d&limit=1"
            ls_ratio = float(requests.get(url_ls, timeout=10).json()[0]['longShortRatio'])

            # Funding Rate (Nhân 100 để ra % luôn cho dễ nhìn)
            url_fr = f"{self.fapi_url}/premiumIndex?symbol={symbol}"
            funding_rate = float(requests.get(url_fr, timeout=10).json()['lastFundingRate']) * 100

            # Open Interest (OI)
            url_oi = f"{self.fapi_url}/openInterest?symbol={symbol}"
            oi = float(requests.get(url_oi, timeout=10).json()['openInterest'])

            return ls_ratio, funding_rate, oi
        except: return 1.0, 0.0, 0.0

    def analyze_coin(self, symbol):
        """Phân tích Full Technical: EMA (7, 25, 99) và RSI"""
        try:
            df_4h = self.get_klines(symbol, "4h", 100)
            df_1d = self.get_klines(symbol, "1d", 100)

            # Tính toán bộ thông số
            price_1d = df_1d['close'].iloc[-1]
            ema25_4h = self.calculate_ema(df_4h, 25)
            ema25_1d = self.calculate_ema(df_1d, 25)
            ema7_1d = self.calculate_ema(df_1d, 7)
            ema99_1d = self.calculate_ema(df_1d, 99)
            rsi_1d = self.calculate_rsi(df_1d)

            # Gói data gửi về để in log
            tech_data = {
                'price': price_1d, 'ema7': ema7_1d, 'ema25': ema25_1d,
                'ema99': ema99_1d, 'rsi': rsi_1d,
                'pass_ema': (df_4h['close'].iloc[-1] > ema25_4h and price_1d > ema25_1d)
            }
            tech_data.update(self.build_trade_plan(df_4h, ema25_4h))
            return tech_data
        except: return None

radar = BinanceRadar()

# ==========================================
# 3. KHỐI LƯU TRỮ & ĐỒNG BỘ CLOUD (GIỮ NGUYÊN)
# ==========================================
_DB_READY = False   # chỉ dựng schema (CREATE/ALTER) 1 lần/tiến trình — các hàm DB gọi init_db() rất nhiều

def init_db(force=False):
    global _DB_READY
    if _DB_READY and not force:
        return
    conn = sqlite3.connect('trading_memory.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS signals (date TEXT, coin TEXT, timeframe TEXT, type TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS money_flow (date TEXT, sector_from TEXT, sector_to TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS bot_state (key TEXT PRIMARY KEY, value TEXT)''')
    # Người đăng ký của từng bot đích (getUpdates thu thập): mỗi bot relay tin tới đây
    c.execute('''CREATE TABLE IF NOT EXISTS bot_subscribers (
        bot_id TEXT, chat_id INTEGER, name TEXT, first_seen TEXT,
        PRIMARY KEY (bot_id, chat_id))''')
    # Blocklist: người bị /unsub → KHÔNG bao giờ poll thêm lại (trừ khi /resub)
    c.execute('''CREATE TABLE IF NOT EXISTS bot_blocklist (
        bot_id TEXT, chat_id INTEGER, ts TEXT,
        PRIMARY KEY (bot_id, chat_id))''')
    # Migrate DB cũ: thêm cột điểm + trade plan cho bảng signals (đã có thì bỏ qua)
    for col in ('score REAL', 'entry REAL', 'stoploss REAL', 'tp1 REAL', 'tp2 REAL'):
        try: c.execute(f'ALTER TABLE signals ADD COLUMN {col}')
        except sqlite3.OperationalError: pass
    conn.commit()
    conn.close()
    _DB_READY = True

def insert_db(table, data, columns=None):
    try:
        init_db()
        conn = sqlite3.connect('trading_memory.db')
        c = conn.cursor()
        placeholders = ', '.join(['?'] * len(data))
        cols = f" ({', '.join(columns)})" if columns else ""
        c.execute(f'INSERT INTO {table}{cols} VALUES ({placeholders})', data)
        conn.commit()
        conn.close()
    except Exception: pass

def get_state(key):
    """Đọc 1 giá trị trạng thái từ bảng bot_state (None nếu chưa có)"""
    try:
        init_db()
        conn = sqlite3.connect('trading_memory.db')
        c = conn.cursor()
        c.execute("SELECT value FROM bot_state WHERE key=?", (key,))
        row = c.fetchone()
        conn.close()
        return row[0] if row else None
    except Exception:
        return None

def set_state(key, value):
    """Ghi đè 1 giá trị trạng thái vào bảng bot_state"""
    try:
        init_db()
        conn = sqlite3.connect('trading_memory.db')
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO bot_state (key, value) VALUES (?, ?)", (key, str(value)))
        conn.commit()
        conn.close()
    except Exception: pass

def _is_blocked(bot_id, chat_id):
    """True nếu chat_id đã bị /unsub khỏi bot này (nằm trong blocklist)."""
    try:
        init_db()
        conn = sqlite3.connect('trading_memory.db')
        c = conn.cursor()
        c.execute("SELECT 1 FROM bot_blocklist WHERE bot_id=? AND chat_id=?", (bot_id, chat_id))
        row = c.fetchone()
        conn.close()
        return row is not None
    except Exception:
        return False

def _upsert_subscriber(bot_id, chat_id, name):
    """Thêm/cập nhật 1 người đăng ký của bot. Trả trạng thái:
      'new'     — vừa thêm mới
      'exists'  — đã có sẵn (cập nhật tên)
      'blocked' — nằm trong blocklist (đã /unsub) → bỏ qua, KHÔNG bao giờ thêm lại
      'error'   — lỗi ghi DB (vd SQLite bị lock) → KHÔNG được nhảy offset, để poll sau đọc lại
    Phân biệt 'error' rất quan trọng: nếu nuốt lỗi rồi vẫn nhảy offset thì update /start mất luôn."""
    if _is_blocked(bot_id, chat_id):
        return 'blocked'
    try:
        init_db()
        conn = sqlite3.connect('trading_memory.db')
        c = conn.cursor()
        c.execute("SELECT 1 FROM bot_subscribers WHERE bot_id=? AND chat_id=?", (bot_id, chat_id))
        is_new = c.fetchone() is None
        if is_new:
            c.execute("INSERT INTO bot_subscribers (bot_id, chat_id, name, first_seen) VALUES (?,?,?,?)",
                      (bot_id, chat_id, name, datetime.datetime.now(VN_TZ).isoformat()))
        else:
            c.execute("UPDATE bot_subscribers SET name=? WHERE bot_id=? AND chat_id=?", (name, bot_id, chat_id))
        conn.commit()
        conn.close()
        return 'new' if is_new else 'exists'
    except Exception:
        return 'error'

def get_subscribers(bot_id):
    """Danh sách (chat_id, name) đã đăng ký bot này."""
    try:
        init_db()
        conn = sqlite3.connect('trading_memory.db')
        c = conn.cursor()
        c.execute("SELECT chat_id, name FROM bot_subscribers WHERE bot_id=?", (bot_id,))
        rows = c.fetchall()
        conn.close()
        return rows
    except Exception:
        return []

def remove_subscriber(bot_id, chat_id):
    """Gỡ 1 người (đã block/xoá bot) khỏi danh sách đăng ký."""
    try:
        init_db()
        conn = sqlite3.connect('trading_memory.db')
        c = conn.cursor()
        c.execute("DELETE FROM bot_subscribers WHERE bot_id=? AND chat_id=?", (bot_id, chat_id))
        conn.commit()
        conn.close()
    except Exception: pass

def block_subscriber(bot_id, chat_id):
    """/unsub: gỡ khỏi subscriber + ghi blocklist để getUpdates KHÔNG poll thêm lại."""
    remove_subscriber(bot_id, chat_id)
    try:
        init_db()
        conn = sqlite3.connect('trading_memory.db')
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO bot_blocklist (bot_id, chat_id, ts) VALUES (?,?,?)",
                  (bot_id, chat_id, datetime.datetime.now(VN_TZ).isoformat()))
        conn.commit()
        conn.close()
    except Exception: pass

def get_blocklist(bot_id):
    """Danh sách (chat_id, ts) đang bị chặn của bot này."""
    try:
        init_db()
        conn = sqlite3.connect('trading_memory.db')
        c = conn.cursor()
        c.execute("SELECT chat_id, ts FROM bot_blocklist WHERE bot_id=?", (bot_id,))
        rows = c.fetchall()
        conn.close()
        return rows
    except Exception:
        return []

def unblock_subscriber(bot_id, chat_id):
    """/resub: bỏ khỏi blocklist để người đó được phép đăng ký lại (qua /start)."""
    try:
        init_db()
        conn = sqlite3.connect('trading_memory.db')
        c = conn.cursor()
        c.execute("DELETE FROM bot_blocklist WHERE bot_id=? AND chat_id=?", (bot_id, chat_id))
        conn.commit()
        conn.close()
    except Exception: pass

def _poll_subscribers_worker(bots):
    """ĐỒNG BỘ (chạy trong thread qua asyncio.to_thread): getUpdates cho từng token,
    lưu chat_id mọi người nhắn bot (private chat). Trả list (label, số_người_mới, lỗi|None).
    LƯU Ý: Telegram chỉ giữ update ~24h — người /start lâu rồi mà không nhắn lại sẽ không bắt được."""
    out = []
    for token, label in bots:
        bot_id = token.split(':', 1)[0]
        offset = get_state(f'gu_offset_{bot_id}')
        # limit=100 cap số update/lần (giảm payload khi backlog lớn); read_timeout 30s vì
        # lần poll đầu (chưa có offset) phải tải toàn bộ backlog ~24h — 10s có thể không đủ.
        params = {"timeout": 0, "allowed_updates": ["message"], "limit": 100}
        if offset:
            params["offset"] = int(offset)
        data = _bot_api(token, "getUpdates", params, read_timeout=30)
        if not data.get('ok'):
            out.append((label, 0, data.get('description', 'lỗi getUpdates')))
            continue
        updates = data.get('result', [])
        new, had_error, max_uid = 0, False, (int(offset) - 1 if offset else None)
        for upd in updates:
            uid = upd.get('update_id', 0)
            max_uid = uid if max_uid is None else max(max_uid, uid)
            chat = (upd.get('message') or {}).get('chat') or {}
            if chat.get('type') == 'private' and chat.get('id') is not None:
                name = (chat.get('username')
                        or ' '.join(x for x in [chat.get('first_name'), chat.get('last_name')] if x)
                        or str(chat['id']))
                st = _upsert_subscriber(bot_id, int(chat['id']), name)
                if st == 'new':
                    new += 1
                elif st == 'error':
                    had_error = True   # ghi DB lỗi → KHÔNG nhảy offset, để poll sau đọc lại update này
        # Chỉ xác nhận (nhảy offset) khi không có update nào ghi DB lỗi — tránh mất /start vĩnh viễn
        if updates and max_uid is not None and not had_error:
            set_state(f'gu_offset_{bot_id}', max_uid + 1)
        out.append((label, new, "ghi DB lỗi, giữ offset để đọc lại" if had_error else None))
    return out

async def poll_subscribers_job():
    """Quét người đăng ký mới cho mọi bot đích (chạy lúc khởi động + định kỳ)."""
    if not TARGET_BOT_TOKENS:
        return
    res = await asyncio.to_thread(_poll_subscribers_worker, list(TARGET_BOT_TOKENS))
    for label, new, err in res:
        if err:
            print(f"   ⚠️ Poll subscriber {label}: {err}")
        elif new:
            print(f"   👥 Bot {label}: +{new} người đăng ký mới")
    set_state('last_subs_poll', datetime.datetime.now(VN_TZ).isoformat())

def get_backup_dir():
    """Ưu tiên Google Drive (ổ G:); chưa mount thì lưu vào Desktop\\Trading_Bot"""
    gdrive_root = r"G:\My Drive"
    if os.path.exists(gdrive_root):
        return os.path.join(gdrive_root, "Trading_Bot")
    desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    if not os.path.exists(desktop):
        # Desktop có thể bị OneDrive chuyển hướng
        onedrive_desktop = os.path.join(os.path.expanduser("~"), "OneDrive", "Desktop")
        if os.path.exists(onedrive_desktop): desktop = onedrive_desktop
    return os.path.join(desktop, "Trading_Bot")

def backup_to_drive():
    """Copy DB tới nơi backup. Trả về đường dẫn folder nếu thành công, None nếu không."""
    try:
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        backup_dir = get_backup_dir()
        if not os.path.exists(backup_dir): os.makedirs(backup_dir)
        if os.path.exists('trading_memory.db'):
            shutil.copy('trading_memory.db', os.path.join(backup_dir, 'trading_memory.db'))
            noi_luu = "Google Drive" if backup_dir.lower().startswith("g:") else "Desktop (ổ G: chưa mount)"
            print(f"\n[{now_str}] ☁️ AUTO-BACKUP: Đã backup Database vào {noi_luu}: {backup_dir}")
            return backup_dir
        return None
    except Exception as e:
        print(f"\nLỗi backup Database: {e}")
        return None

# ==========================================
# 4. KHỐI BÁO CÁO (ANALYTICS)
# ==========================================
def generate_report(is_auto=False):
    init_db()
    conn = sqlite3.connect('trading_memory.db')
    prefix = "⏰ **BẢN TIN ĐIỂM TÂM VIP (V6)**" if is_auto else "📊 **BÁO CÁO TRỰC TIẾP (V6)**"
    report = f"{prefix}\n\n"
    now_date = datetime.datetime.now().strftime("%Y-%m-%d")

    try:
        df_flow = pd.read_sql_query(f"SELECT sector_to FROM money_flow WHERE date LIKE '{now_date}%'", conn)
        if not df_flow.empty:
            top_sectors = df_flow['sector_to'].value_counts().head(3).to_dict()
            report += f"**🔥 TOP NGÀNH HÚT TIỀN (HÔM NAY):**\n"
            for s, c in top_sectors.items(): report += f"  • {s}: {c} lần bơm\n"
        else: report += "**🔥 TOP NGÀNH HÚT TIỀN:** ⏳ Chưa có dòng tiền mới hôm nay.\n"

        df_signals = pd.read_sql_query(f"SELECT coin, timeframe, type, score, entry, stoploss, tp1, tp2 FROM signals WHERE type LIKE 'BUY_HOA_HAU%' AND date LIKE '{now_date}%'", conn)
        if not df_signals.empty:
            # Mỗi coin lấy bản ghi mới nhất, xếp hạng theo điểm đáng giá giảm dần
            df_signals['score'] = df_signals['score'].fillna(0)
            latest = df_signals.groupby('coin', sort=False).last()
            counts = df_signals['coin'].value_counts()
            ranked = latest.sort_values('score', ascending=False)

            # TOP PICK: hạng 1 luôn vào, hạng 2 vào nếu điểm >= 70
            top_coins = list(ranked.index[:1])
            if len(ranked) > 1 and ranked['score'].iloc[1] >= 70:
                top_coins.append(ranked.index[1])

            report += f"\n**🏆 TOP KÈO ĐÁNG GIÁ NHẤT HÔM NAY:**\n"
            for c in top_coins:
                row = ranked.loc[c]
                icon = "🌟" if row['type'] == 'BUY_HOA_HAU_VIP' else "✅"
                report += f"  🏆 {icon} **{c}** — 💯 {row['score']:.0f}/100 | Báo {counts[c]} lần | {row['timeframe']}\n"
                if pd.notna(row['entry']):
                    report += (f"      📥 Entry: {fmt_price(row['entry'])} | 🛑 SL: {fmt_price(row['stoploss'])}"
                               f" | 🎯 TP1: {fmt_price(row['tp1'])} / TP2: {fmt_price(row['tp2'])}\n")

            others = [c for c in ranked.index if c not in top_coins]
            if others:
                report += f"\n**🎯 CÁC KÈO HOA HẬU KHÁC (PASS EMA 4H/1D):**\n"
                for c in others:
                    row = ranked.loc[c]
                    if row['type'] == 'BUY_HOA_HAU_VIP':
                        report += f"  🌟 **{c}**: 💯 {row['score']:.0f} | Báo {counts[c]} lần ({row['timeframe']})\n"
                    else:
                        report += f"  ✅ {c}: 💯 {row['score']:.0f} | Báo {counts[c]} lần ({row['timeframe']})\n"
        else: report += "\n**🎯 KÈO HOA HẬU:** ⏳ Chưa có mã nào vượt EMA25.\n"

        df_xit = pd.read_sql_query(f"SELECT type, COUNT(*) as cnt FROM signals WHERE type LIKE 'XIT_%' AND date LIKE '{now_date}%' GROUP BY type", conn)
        if not df_xit.empty:
            report += f"\n**🛡️ CÁC KÈO ĐÃ BỎ QUA (HÔM NAY):**\n"
            for _, row in df_xit.iterrows(): report += f"  • {row['type']}: {row['cnt']} lệnh\n"
    except Exception as e: report += f"Lỗi xuất báo cáo: {e}"
    conn.close()
    return report

# ==========================================
# 5. NGƯỜI GÁC CỔNG V6 (FULL OPTION BINANCE)
# ==========================================
def fmt_price(p):
    """Format giá theo độ lớn — coin to ít số lẻ, coin rác nhiều số lẻ"""
    if p >= 100: return f"{p:,.2f}"
    if p >= 1: return f"{p:.4f}"
    if p >= 0.01: return f"{p:.6f}"
    return f"{p:.8f}"

def compute_score(tech, ls_ratio, fr, weather, total_mentions, is_vip, force_urgent):
    """Chấm điểm độ đáng giá của kèo (0-100) — gom trí tuệ từ DB + Binance.
    Nền 50 điểm (đã pass kỹ thuật), cộng/trừ theo từng yếu tố."""
    score = 50.0
    if is_vip: score += 10                                   # đủ bộ thiên thời địa lợi
    score += min(max(total_mentions - 2, 0) * 5, 15)         # DB: càng nhiều nguồn nhắc càng uy tín
    if force_urgent: score += 5                              # nguồn khẩn cấp (Watchlist/Excel)
    if 45 <= tech['rsi'] <= 65: score += 10                  # RSI vùng đẹp: còn dư địa tăng
    elif tech['rsi'] > 75: score -= 10                       # vùng FOMO
    if ls_ratio > 1.5: score += 5
    elif ls_ratio > 1.0: score += 3
    elif ls_ratio < 0.8: score -= 5
    if fr < 0: score += 5                                    # funding âm: short trả tiền cho long
    elif fr > 0.05: score -= 5                               # long quá nóng
    if tech['price'] > tech['ema7'] > tech['ema25'] > tech['ema99']: score += 10  # EMA xếp tầng hoàn hảo
    if "NẮNG ĐẸP" in weather: score += 10
    elif "BÃO TỐ" in weather: score -= 15
    if tech['price'] > tech['ema25'] * 1.15: score -= 5      # giá chạy quá xa EMA25, dễ đu đỉnh
    return round(min(max(score, 0), 100))

def get_today_rank(coin, score, today):
    """Xếp hạng điểm này so với các kèo chốt KHÁC trong ngày (điểm cao nhất mỗi coin).
    Trả về hạng 1-based — hạng 1 = đáng giá nhất hôm nay."""
    try:
        conn = sqlite3.connect('trading_memory.db')
        c = conn.cursor()
        c.execute("SELECT coin, MAX(COALESCE(score, 0)) FROM signals WHERE type LIKE 'BUY_HOA_HAU%' AND date LIKE ? AND coin != ? GROUP BY coin", (f"{today}%", coin))
        others = [row[1] for row in c.fetchall()]
        conn.close()
        return sum(1 for s in others if s > score) + 1
    except Exception:
        return 99

def format_trade_plan(tech):
    """Khối Entry/SL/TP kèm % so với entry để dán vào tin nhắn"""
    entry, sl, tp1, tp2 = tech['entry'], tech['sl'], tech['tp1'], tech['tp2']
    return (f"📥 Entry: {fmt_price(entry)} - SL: {fmt_price(sl)} ({(sl/entry - 1)*100:.1f}%) - "
            f"TP1: {fmt_price(tp1)} (+{(tp1/entry - 1)*100:.1f}%) | TP2: {fmt_price(tp2)} (+{(tp2/entry - 1)*100:.1f}%)")

async def check_and_evaluate(coin, now, force_urgent=False, source="", extra_tf=None):
    try:
        conn = sqlite3.connect('trading_memory.db')
        c = conn.cursor()
        today = now[:10]
        c.execute("SELECT COUNT(*) FROM signals WHERE coin=? AND date LIKE ?", (coin, f"{today}%"))
        sig_count = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM money_flow WHERE sector_to=? AND date LIKE ?", (coin, f"{today}%"))
        flow_count = c.fetchone()[0]
        total_mentions = sig_count + flow_count
        conn.close()

        if total_mentions >= 2 or force_urgent:
            reason = source if force_urgent else f"GOM ĐƯỢC {total_mentions} TÍN HIỆU NGẮN HẠN"
            print(f"\n[{now}] 🚨 KÍCH HOẠT MẮT THẦN V6: {coin} ({reason})")

            # --- BƯỚC 1: SOI KỸ THUẬT TOÀN DIỆN ---
            tech = radar.analyze_coin(f"{coin}USDT")
            if not tech:
                # Thường gặp: coin chưa niêm yết Binance Spot (cặp USDT) → get_klines trả lỗi
                # "Invalid symbol", analyze_coin nuốt exception trả None. In rõ để không "biến mất" im lặng.
                print(f"   ⚠️ Bỏ qua {coin}: không lấy được dữ liệu Binance Spot ({coin}USDT) — có thể chưa niêm yết / sai symbol.")
                return

            # In Log siêu chi tiết như 1 Quant Trader thực thụ
            print(f"   📊 [Kỹ thuật] Giá: {tech['price']:.4f} | EMA(7/25/99): ({tech['ema7']:.4f} / {tech['ema25']:.4f} / {tech['ema99']:.4f}) | RSI: {tech['rsi']:.2f}")

            if not tech['pass_ema']:
                print(f"   ❌ Loại {coin}: Cấu trúc giá yếu (Dưới EMA25 4H/1D)")
                insert_db('signals', (now, coin, "4h_1d_check", "XIT_KY_THUAT"),
                          columns=('date', 'coin', 'timeframe', 'type'))
                return

            # --- GATE TP1: pass kỹ thuật nhưng TP1 quá hẹp (< +10%) → loại, KHÔNG broadcast ---
            # Loại SỚM (trước BƯỚC 2/3): không tốn HTTP phái sinh, không chấm điểm/xếp hạng.
            # Ghi type riêng XIT_TP_HEP để báo cáo đếm vào "kèo đã bỏ qua", KHÔNG lẫn kèo chốt.
            tp1_pct = (tech['tp1'] / tech['entry'] - 1) * 100
            if tp1_pct < 10:
                print(f"   🔇 Loại {coin}: TP1 chỉ +{tp1_pct:.1f}% (< 10%) — ghi XIT_TP_HEP, KHÔNG phát.")
                insert_db('signals',
                          (now, coin, f"TP1+{tp1_pct:.1f}%", "XIT_TP_HEP",
                           tech['entry'], tech['sl'], tech['tp1'], tech['tp2']),
                          columns=('date', 'coin', 'timeframe', 'type',
                                   'entry', 'stoploss', 'tp1', 'tp2'))
                return

            # --- BƯỚC 2: QUÉT BENCHMARK & PHÁI SINH ---
            weather = radar.check_market_weather()
            ls_ratio, fr, oi = radar.spy_on_derivatives(f"{coin}USDT")

            print(f"   🌊 [Dòng chảy] TT: {weather} | L/S: {ls_ratio:.2f} | Funding: {fr:.4f}% | OI: {oi:,.0f}")

            # Đóng gói chuỗi báo cáo để gửi vào Tele
            stats_info = f"RSI: {tech['rsi']:.0f} | L/S: {ls_ratio:.2f} | FR: {fr:.4f}%"

            # Logic VIP Khắc nghiệt: Mọi thứ phải hoàn hảo (Ko dính FOMO RSI > 75)
            is_vip = ("NẮNG ĐẸP" in weather) and (ls_ratio > 1.0) and (tech['rsi'] < 75)

            # --- BƯỚC 3: CHẤM ĐIỂM & XẾP HẠNG TRONG NGÀY ---
            score = compute_score(tech, ls_ratio, fr, weather, total_mentions, is_vip, force_urgent)
            rank = get_today_rank(coin, score, today)
            # TOP PICK: đứng nhất hôm nay, hoặc đứng nhì nhưng điểm vẫn rất cao (>= 70)
            is_top = (rank == 1) or (rank == 2 and score >= 70)

            sig_type = "BUY_HOA_HAU_VIP" if is_vip else "BUY_HOA_HAU"
            # Nhãn theo nguồn tín hiệu (ưu tiên nguồn đặc biệt trước nhãn VIP/Thường)
            is_watchlist = "WATCHLIST" in source.upper()
            is_rotation = source.upper().startswith("ROTATION:")
            if is_rotation:
                # Dòng tiền luân chuyển: nhãn riêng 2 dòng (header + cặp X → Y)
                coin_from = source.split(":", 1)[1]
                label = f"⚡ SMART MONEY ROTATION\n💰 {coin_from} → {coin}"
            elif is_watchlist:
                # Kèo từ Watchlist đột biến: nhãn riêng "Watchlist" (giữ icon theo loại thật 🌟/✅)
                label = f"{'🌟' if is_vip else '✅'} Watchlist: {coin}"
            # Top pick được nâng nhãn lên KÈO VIP kể cả khi thiếu bonus vĩ mô
            elif is_vip or is_top:
                label = f"{'🌟' if is_vip else '✅'} KÈO VIP: {coin}"
            else:
                label = f"✅ KÈO THƯỜNG: {coin}"
            print(f"   {'🌟 CHỐT KÈO VIP' if is_vip else '✅ CHỐT KÈO THƯỜNG'} {coin} | 💯 Điểm: {score}/100 (hạng {rank} hôm nay)"
                  + (" | 🏆 TOP PICK" if is_top else ""))

            insert_db('signals', (now, coin, stats_info, sig_type, score, tech['entry'], tech['sl'], tech['tp1'], tech['tp2']),
                      columns=('date', 'coin', 'timeframe', 'type', 'score', 'entry', 'stoploss', 'tp1', 'tp2'))

            # TF (kèo từ Excel) CHỈ gắn vào tin broadcast tức thời — KHÔNG lưu DB
            # nên /stats và báo cáo 07:00/16:00 (đọc từ DB) sẽ không hiển thị TF.
            stats_line = stats_info + (f" | TF: {extra_tf}" if extra_tf else "")
            msg = (f"{label}\n"
                   f"💯 Điểm: {score}/100 (hạng {rank} hôm nay)\n"
                   f"{format_trade_plan(tech)}\n"
                   f"{stats_line}")
            if is_top:
                msg = f"🏆🏆🏆 TOP PICK 🏆🏆🏆\n{msg}"
            await broadcast_to_bots(msg)

    except Exception as e: print("Lỗi soi chéo:", e)

CONV_DEFAULT_DESC = "Nhiều nguồn vốn cùng chảy về 1 coin"
MFI_DEFAULT_DESC = "Dòng tiền đột biến"

async def convergence_alert(coin, desc, now, title="👀Capital Convergence",
                            default_desc=CONV_DEFAULT_DESC, log_tag="CAPITAL CONVERGENCE"):
    """Cảnh báo NHANH cho tin Capital Convergence / MFI Breakout — bắn ngay khi đạt điều kiện,
    KHÔNG qua gác cổng EMA và KHÔNG ghi bảng signals (tránh cộng lượt nhắc ảo —
    luồng RAW_URGENT của Watchlist vẫn chạy song song như cũ).
    Điều kiện bắn: (|biến động 24h| < 10%  HOẶC  giá còn trong dải Bollinger MA99 1H) VÀ TP1 ≥ +10%.
    `title`/`default_desc`/`log_tag` cho phép tái dụng cho nhiều loại tín hiệu (mặc định = Capital Convergence)."""
    try:
        print(f"\n[{now}] 👀 {log_tag}: {coin} — soi nhanh khung 1H/4H...")
        plan = radar.analyze_convergence(f"{coin}USDT")
        if not plan:
            print(f"   ⚠️ {coin}: không lấy được dữ liệu Binance — bỏ qua cảnh báo nhanh.")
            return
        print(f"   📊 Biến động 24h: {plan['change_24h']:+.1f}% | Trong dải BB MA99 1H: {'CÓ' if plan['in_bb'] else 'KHÔNG'}")
        if abs(plan['change_24h']) >= 10 and not plan['in_bb']:
            print(f"   ❌ {coin}: đã chạy {plan['change_24h']:+.1f}% và thoát dải BB — KHÔNG cảnh báo.")
            return
        tp1_pct = (plan['tp1'] / plan['entry'] - 1) * 100
        if tp1_pct < 10:
            print(f"   🔇 {coin}: TP1 chỉ +{tp1_pct:.1f}% (< 10%) — KHÔNG cảnh báo nhanh.")
            return
        msg = (f"{title}\n"
               f"✅{coin}: {desc or default_desc}\n"
               f"{format_trade_plan(plan)}")
        await broadcast_to_bots(msg)
        print(f"   🚀 Đã bắn cảnh báo nhanh {coin} | {format_trade_plan(plan)}")
    except Exception as e:
        print(f"   ⚠️ Lỗi cảnh báo nhanh {coin}: {e}")

async def broadcast_market_status(file_path, now):
    """Đọc sheet 'Buy Sell Bar' trong file signals_v4 → broadcast tổng quan thị trường
    (đếm BUY/SELL theo từng khung) NGAY, TRƯỚC khi xử lý tín hiệu từng coin.
    Sheet dạng: cột timeframe | BUY | SELL, mỗi khung 1 dòng (vd 1d, 4h)."""
    xl = pd.ExcelFile(file_path)
    sheet = next((s for s in xl.sheet_names if s.strip().lower() == 'buy sell bar'), None)
    if not sheet:
        print(f"[{now}] ℹ️ File không có sheet 'Buy Sell Bar' — bỏ qua Market Status.")
        return
    df = pd.read_excel(xl, sheet_name=sheet)
    df.columns = [str(c).strip().upper() for c in df.columns]
    tf_col = next((c for c in df.columns if 'TIMEFRAME' in c or c == 'TF'), None)
    buy_col = next((c for c in df.columns if c == 'BUY'), None)
    sell_col = next((c for c in df.columns if c == 'SELL'), None)
    if not (tf_col and buy_col and sell_col):
        print(f"[{now}] ⚠️ Sheet 'Buy Sell Bar' thiếu cột timeframe/BUY/SELL — bỏ qua Market Status.")
        return

    def _to_int(v):
        try: return int(float(v))
        except Exception: return None

    def _disp(v):
        n = _to_int(v)
        return str(n) if n is not None else str(v).strip()

    counts = {}   # tf (chuẩn hóa hoa) -> (buy_raw, sell_raw)
    for _, row in df.iterrows():
        tf = str(row[tf_col]).strip().upper()
        if tf and tf != 'NAN':
            counts[tf] = (row[buy_col], row[sell_col])

    lines = ["⚠️ Market Status:"]
    for tf in ('1D', '4H'):   # giữ đúng thứ tự 1D rồi 4H như format yêu cầu
        if tf in counts:
            b, s = counts[tf]
            lines.append(f"📊 {tf}: 🟢Buy/🔴Sell - {_disp(b)}/{_disp(s)}")

    # Kết luận theo khung 4H: áp đảo khi 1 phía gấp >= 2 lần phía còn lại
    bi, si = (_to_int(counts['4H'][0]), _to_int(counts['4H'][1])) if '4H' in counts else (None, None)
    if bi is not None and si is not None:
        if bi > 0 and bi >= 2 * si:
            lines.append("Buy đang áp đảo, yên tâm giữ hàng")
        elif si > 0 and si >= 2 * bi:
            lines.append("Sell đang áp đảo, cực kỳ cẩn thận")

    if len(lines) > 1:
        await broadcast_to_bots("\n".join(lines))
        print(f"[{now}] 🚀 Đã broadcast Market Status: {counts}")

async def process_source_message(message):
    """Xử lý 1 tin nhắn từ bot nguồn — dùng chung cho tin real-time và tin đọc bù lúc khởi động.
    Mốc thời gian lấy theo giờ GỬI của tin (đổi sang giờ VN) để tin đọc bù vẫn đếm đúng ngày."""
    try:
        text = message.raw_text
        now = message.date.astimezone(VN_TZ).strftime("%Y-%m-%d %H:%M:%S")

        if message.media and hasattr(message.media, 'document'):
            doc = message.media.document
            mime_type = doc.mime_type
            if 'spreadsheetml' in mime_type or 'excel' in mime_type or 'csv' in mime_type:
                # CHỈ lấy file có tên chứa 'signals_v4' — bot nguồn có thể gửi nhiều Excel,
                # các file khác bỏ qua hoàn toàn (không tải về, không phân tích).
                fname = (message.file.name or '') if message.file else ''
                if 'signals_v4' not in fname.lower():
                    print(f"[{now}] 📎 Bỏ qua file Excel '{fname}' — chỉ xử lý file chứa 'signals_v4'.")
                    return
                file_path = await message.download_media(file='temp_data.xlsx')
                # Broadcast tổng quan thị trường (sheet 'Buy Sell Bar') NGAY, TRƯỚC khi xử lý tín hiệu.
                # Chỉ với file Excel (CSV không có nhiều sheet); lỗi ở đây KHÔNG được chặn xử lý tín hiệu.
                if 'excel' in mime_type or 'spreadsheetml' in mime_type:
                    try:
                        await broadcast_market_status(file_path, now)
                    except Exception as e:
                        print(f"[{now}] ⚠️ Bỏ qua Market Status (lỗi đọc sheet Buy Sell Bar): {e}")
                try:
                    df = pd.read_excel(file_path) if 'excel' in mime_type or 'spreadsheetml' in mime_type else pd.read_csv(file_path)
                    df.columns = [str(c).strip().upper() for c in df.columns]
                    # Lấy chính xác cột PRIORITY_SCORE
                    score_col = 'PRIORITY_SCORE' if 'PRIORITY_SCORE' in df.columns else None
                    coin_col = next((c for c in df.columns if 'SYMBOL' in c or 'COIN' in c), None)
                    tf_col = next((c for c in df.columns if 'TIMEFRAME' in c or c == 'TF'), None)
                    signal_col = next((c for c in df.columns if 'SIGNAL' in c or 'DIRECTION' in c), None)
                    ts_col = next((c for c in df.columns if 'TIMESTAMP' in c), None)
                    if score_col and coin_col:
                        df[score_col] = pd.to_numeric(df[score_col], errors='coerce')
                        sel = df[df[score_col] >= 70].copy()
                        # Chỉ lấy BUY khi file có cột signal (file không có cột → xử lý hết như cũ)
                        if signal_col:
                            sel = sel[sel[signal_col].astype(str).str.strip().str.upper() == 'BUY']
                        if not sel.empty:
                            # Khử trùng theo (coin, timeframe) — giữ dòng timestamp mới nhất.
                            # check_and_evaluate luôn phân tích live Binance (bỏ qua entry/TP trong
                            # file) nên cùng 1 coin nhiều dòng chỉ tạo các tin gần như y hệt → gộp.
                            sel['__coin'] = sel[coin_col].astype(str).str.upper().str.replace('/USDT', '', regex=False).str.strip()
                            sel['__tf'] = sel[tf_col].astype(str).str.strip().str.upper() if tf_col else ''
                            if ts_col:
                                sel['__ts'] = pd.to_datetime(sel[ts_col], errors='coerce')
                                sel = sel.sort_values('__ts', kind='stable')
                            sel = sel.drop_duplicates(['__coin', '__tf'], keep='last')
                            for _, row in sel.iterrows():
                                raw_coin = row['__coin']
                                tf_val = str(row[tf_col]).strip().upper() if (tf_col and pd.notna(row[tf_col])) else None
                                insert_db('signals', (now, raw_coin, "excel", "RAW_EXCEL"),
                                          columns=('date', 'coin', 'timeframe', 'type'))
                                await check_and_evaluate(raw_coin, now, force_urgent=True, source=f"EXCEL_SCORE_{row[score_col]}", extra_tf=tf_val)
                except Exception as e: pass
                finally:
                    if os.path.exists(file_path): os.remove(file_path)
                return

        if not text: return

        # --- HỦY coin "đổi sang RS Divergence" (mục "Cập nhật tín hiệu") ---
        # Coin đã đổi sang RS Divergence → BỎ QUA, không phân tích ở 3 luồng tức thời bên dưới
        # (Watchlist / Capital Convergence / MFI Breakout); đồng thời xóa RAW_URGENT đã ghi hôm
        # nay (kể cả từ tin trước) để không còn cộng lượt nhắc cho coin đó.
        cancelled_coins = set()
        if 'cập nhật tín hiệu' in text.lower():
            for c in re.findall(r'([A-Za-z0-9]+)\s*[:：—\-–]\s*đổi\s+sang\s+RS\s+Divergence',
                                text, re.IGNORECASE):
                cancelled_coins.add(c.strip().upper())
            if cancelled_coins:
                print(f"[{now}] 🚫 Đổi sang RS Divergence → bỏ qua: {', '.join(sorted(cancelled_coins))}")
                try:
                    conn = sqlite3.connect('trading_memory.db')
                    cur = conn.cursor()
                    for c in cancelled_coins:
                        cur.execute("DELETE FROM signals WHERE coin=? AND type='RAW_URGENT' AND date LIKE ?",
                                    (c, f"{now[:10]}%"))
                    conn.commit()
                    conn.close()
                except Exception as e:
                    print(f"   ⚠️ Lỗi xóa RAW_URGENT cho coin đổi sang RS Divergence: {e}")

        # Tin Capital Convergence → cảnh báo NHANH (chạy TRƯỚC gác cổng để kịp "ngay lập tức")
        if 'capital convergence' in text.lower():
            for coin, desc in re.findall(
                    r'•\s*([A-Za-z0-9]+)\s*[—\-–]\s*Capital\s+Convergence\s*:?\s*([^\n]*)',
                    text, re.IGNORECASE):
                coin = coin.strip().upper()
                if coin in cancelled_coins: continue
                await convergence_alert(coin, desc.strip(), now)

        # Tin MFI Breakout → cảnh báo NHANH y hệt Capital Convergence (mục 3c), chỉ khác tiêu đề.
        # Dạng dòng: "AI — MFI Breakout: <mô tả>" (coin đứng đầu, không cần dấu •).
        if 'mfi breakout' in text.lower():
            for coin, desc in re.findall(
                    r'([A-Za-z0-9]+)\s*[—\-–]\s*MFI\s+Breakout\s*:?\s*([^\n]*)',
                    text, re.IGNORECASE):
                coin = coin.strip().upper()
                if coin in cancelled_coins: continue
                await convergence_alert(coin, "", now,
                                        title="👀 MFI Breakout kèm volume cao",
                                        default_desc=MFI_DEFAULT_DESC,
                                        log_tag="MFI BREAKOUT")

        if "Watchlist" in text and "Mới thêm" in text:
            urgent_coins = re.findall(r'•\s*(.*?)\s*[—\-]', text)
            for coin in urgent_coins:
                coin = coin.strip().upper()
                if coin in cancelled_coins: continue
                insert_db('signals', (now, coin, "watchlist", "RAW_URGENT"),
                          columns=('date', 'coin', 'timeframe', 'type'))
                await check_and_evaluate(coin, now, force_urgent=True, source="WATCHLIST ĐỘT BIẾN")

        # Dòng tiền luân chuyển: CHỈ xử lý tin có header "SMART MONEY ROTATION",
        # bắt MỌI cặp X → Y trong tin (mỗi coin đích được ghi & đánh giá riêng).
        if 'smart money rotation' in text.lower():
            for coin_from, coin_to in re.findall(r'([A-Za-z0-9]+)\s*→\s*([A-Za-z0-9]+)', text):
                coin_from = coin_from.upper()
                coin_to = coin_to.upper()
                insert_db('money_flow', (now, coin_from, coin_to))
                await check_and_evaluate(coin_to, now, source=f"ROTATION:{coin_from}")

        # Định dạng "Deep Analysis": tin có header "Deep Analysis", mỗi tín hiệu 1 dòng
        # dạng "🟢 1. BANANA/USDT [BUY]" — bắt MỌI dòng, chỉ ghi nhận [BUY], bỏ qua [SELL].
        if 'deep analysis' in text.lower():
            for coin, direction in re.findall(r'\d+\.\s*([A-Z0-9]+)/USDT\s*\[(BUY|SELL)\]', text, re.IGNORECASE):
                if direction.upper() != 'BUY':
                    continue
                coin = coin.upper()
                insert_db('signals', (now, coin, 'text', "RAW_SIGNAL"),
                          columns=('date', 'coin', 'timeframe', 'type'))
                await check_and_evaluate(coin, now)

    except Exception as e: pass
    finally:
        # Ghi mốc tin cuối đã xử lý — để lần khởi động sau biết đọc bù từ đâu
        try:
            if message.id > int(get_state('last_msg_id') or 0):
                set_state('last_msg_id', message.id)
        except Exception: pass

@client.on(events.NewMessage(chats=SOURCE_BOT, incoming=True))
async def main_handler(event):
    """Chỉ xử lý tin nhắn ĐẾN TỪ bot nguồn (SOURCE_BOT)"""
    await process_source_message(event.message)

@client.on(events.NewMessage(outgoing=True))
async def command_handler(event):
    """Lệnh điều khiển — CHỈ nhận trong Saved Messages (chat với chính mình), chat khác bỏ qua"""
    try:
        if MY_ID is None or event.chat_id != MY_ID:   # chỉ Saved Messages mới điều khiển được
            return
        text = (event.raw_text or '').strip().lower()
        if text == '/stats':
            await event.reply("⚙️ Đang lên báo cáo dòng tiền tổng hợp V6...")
            await event.reply(generate_report())
        elif text == '/backup':
            dest = backup_to_drive()
            if dest:
                await event.reply(f"☁️ Đã backup Database vào: {dest}")
            else:
                await event.reply("⚠️ Backup chưa chạy được (DB chưa tồn tại hoặc lỗi ghi — xem log console)")
        elif text == '/test':
            await event.reply("🧪 Đang tự kiểm tra: Binance + Database + kênh gửi bot đích...")
            results = []

            tech = radar.analyze_coin("BTCUSDT")
            if tech:
                results.append(f"✅ Binance Spot: OK (BTC giá {tech['price']:,.0f} | RSI {tech['rsi']:.1f})")
            else:
                results.append("❌ Binance Spot: không lấy được dữ liệu klines")

            weather = radar.check_market_weather()
            if weather != "LỖI KẾT NỐI":
                results.append(f"✅ Binance Futures: OK (Thời tiết: {weather})")
            else:
                results.append("❌ Binance Futures: lỗi kết nối")

            try:
                init_db()
                results.append("✅ Database SQLite: OK")
            except Exception as e:
                results.append(f"❌ Database SQLite: {e}")

            for token, label in TARGET_BOT_TOKENS:
                me_data = await asyncio.to_thread(_bot_api, token, "getMe", None)
                if me_data.get('ok'):
                    uname = me_data['result'].get('username', '?')
                    nsubs = len(get_subscribers(token.split(':', 1)[0]))
                    note = "" if nsubs else " — chưa ai đăng ký, nhờ người tạo bot /start lại"
                    results.append(f"✅ Bot {label} (@{uname}): token OK, {nsubs} người đăng ký{note}")
                else:
                    results.append(f"❌ Bot {label}: token lỗi — {me_data.get('description', '')}")
                await asyncio.sleep(0.2)

            results.append(f"\n📡 Nguồn đang nghe: {SOURCE_BOT}")
            results.append("ℹ️ /test chỉ kiểm tra token + đếm người đăng ký (không gửi tin tới họ). Gõ /subs để quét & xem danh sách.")
            await event.reply("🧪 **KẾT QUẢ TỰ KIỂM TRA:**\n" + "\n".join(results))
        elif text == '/subs':
            await event.reply("👥 Đang quét người đăng ký các bot đích (getUpdates)...")
            await poll_subscribers_job()
            lines = []
            for token, label in TARGET_BOT_TOKENS:
                subs = get_subscribers(token.split(':', 1)[0])
                if subs:
                    who = '\n'.join(f"   - {n} ({c})" for c, n in subs)   # kèm chat_id để gỡ bằng /unsub
                    lines.append(f"• {label}: {len(subs)} người\n{who}")
                else:
                    lines.append(f"• {label}: 0 người — (chưa có ai; nhờ người tạo bot nhắn /start khi tool đang chạy)")
            lines.append("\nℹ️ Gỡ vĩnh viễn: /unsub <bot> <chat_id> | Cho phép lại: /resub <bot> <chat_id> | Xem chặn: /blocked")
            await event.reply("👥 **NGƯỜI ĐĂNG KÝ THEO BOT:**\n" + "\n".join(lines))
        elif text == '/blocked':
            lines = []
            for token, label in TARGET_BOT_TOKENS:
                blocked = get_blocklist(token.split(':', 1)[0])
                if blocked:
                    who = '\n'.join(f"   - {c} (chặn lúc {ts[:16].replace('T', ' ')})" for c, ts in blocked)
                    lines.append(f"• {label}: {len(blocked)} bị chặn\n{who}")
                else:
                    lines.append(f"• {label}: 0 bị chặn")
            lines.append("\nℹ️ Bỏ chặn: /resub <bot> <chat_id>")
            await event.reply("🚫 **DANH SÁCH BỊ CHẶN:**\n" + "\n".join(lines))
        elif text.startswith('/unsub') or text.startswith('/resub'):
            is_unsub = text.startswith('/unsub')
            cmd = '/unsub' if is_unsub else '/resub'
            parts = (event.raw_text or '').split()
            if len(parts) != 3:
                await event.reply(f"Cú pháp: {cmd} <tên_bot hoặc bot_id> <chat_id>\nVí dụ: {cmd} xitrumm 6342103299 (gõ /subs để xem chat_id)")
                return
            _, bot_arg, chat_arg = parts
            bot_id = label_found = None
            for token, label in TARGET_BOT_TOKENS:
                bid = token.split(':', 1)[0]
                if bot_arg.lower() == label.lower() or bot_arg == bid:
                    bot_id, label_found = bid, label
                    break
            if bot_id is None:
                await event.reply(f"❌ Không tìm thấy bot '{bot_arg}'. Gõ /subs xem danh sách.")
                return
            try:
                cid = int(chat_arg)
            except ValueError:
                await event.reply("❌ chat_id phải là số. Gõ /subs để xem chat_id.")
                return
            if is_unsub:
                block_subscriber(bot_id, cid)   # gỡ + chặn poll thêm lại
                await event.reply(f"🚫 Đã gỡ & CHẶN {cid} khỏi {label_found}. Người này sẽ KHÔNG được thêm lại dù có nhắn bot — gõ /resub {label_found} {cid} để cho phép lại.")
            else:
                unblock_subscriber(bot_id, cid)   # bỏ chặn; họ /start lại sẽ được đăng ký
                await event.reply(f"✅ Đã bỏ chặn {cid} ở {label_found}. Người này /start lại bot sẽ được nhận tin trở lại.")
    except Exception as e: pass

# ==========================================
# 6. BÁO THỨC & KHỞI CHẠY
# ==========================================
async def catch_up_source_messages():
    """Đọc bù các tin bot nguồn đã gửi trong lúc tool tắt (mốc = ID tin cuối đã xử lý, lưu trong DB)"""
    try:
        last_id = get_state('last_msg_id')
        if not last_id:
            # Lần chạy đầu tiên: chưa có mốc — chỉ ghi nhận tin mới nhất làm mốc, không cày lại lịch sử cũ
            msgs = await client.get_messages(SOURCE_BOT, limit=1)
            if msgs: set_state('last_msg_id', msgs[0].id)
            print("   ⏩ Lần chạy đầu: chưa có mốc cũ — bỏ qua lịch sử, chỉ xử lý tin mới từ bây giờ.")
            return
        missed = [m async for m in client.iter_messages(SOURCE_BOT, min_id=int(last_id), reverse=True) if not m.out]
        if not missed:
            print("   ✅ Không có tin nhắn nào bị lỡ trong lúc tool tắt.")
            return
        if len(missed) > 300:
            print(f"   ⚠️ Bị lỡ tới {len(missed)} tin — chỉ đọc bù 300 tin mới nhất, bỏ qua phần cũ hơn.")
            missed = missed[-300:]
        dau = missed[0].date.astimezone(VN_TZ).strftime('%d/%m %H:%M')
        cuoi = missed[-1].date.astimezone(VN_TZ).strftime('%d/%m %H:%M')
        print(f"   📥 Đọc bù {len(missed)} tin bị lỡ từ {SOURCE_BOT} ({dau} → {cuoi})...")
        for msg in missed:
            await process_source_message(msg)
        print(f"   ✅ Xử lý xong {len(missed)} tin đọc bù.")
    except Exception as e:
        print(f"   ⚠️ Lỗi đọc bù tin nhắn: {e}")

def _last_due_report_time(now_vn):
    """Mốc báo cáo định kỳ (07:00 / 16:00 giờ VN) gần nhất đã trôi qua"""
    candidates = []
    for d in (0, 1):
        day = now_vn.date() - datetime.timedelta(days=d)
        for h in (7, 16):
            t = VN_TZ.localize(datetime.datetime.combine(day, datetime.time(h, 0)))
            if t <= now_vn: candidates.append(t)
    return max(candidates)

async def catch_up_missed_report():
    """Tool chết qua mốc 07:00/16:00 chưa kịp gửi báo cáo → gửi bù ngay khi bật lại"""
    try:
        now_vn = datetime.datetime.now(VN_TZ)
        due = _last_due_report_time(now_vn)
        last_sent = get_state('last_report_sent')
        if last_sent is None:
            # Lần chạy đầu tiên: lấy mốc hiện tại, không gửi bù
            set_state('last_report_sent', now_vn.isoformat())
            return
        if datetime.datetime.fromisoformat(last_sent) < due:
            print(f"   ⏰ Lỡ báo cáo định kỳ mốc {due.strftime('%H:%M ngày %d/%m')} — gửi bù ngay...")
            await auto_send_report(missed_at=due)
    except Exception as e:
        print(f"   ⚠️ Lỗi kiểm tra báo cáo gửi bù: {e}")

async def auto_send_report(missed_at=None):
    report = generate_report(is_auto=True)
    if missed_at:
        report = (f"⏰ **BÁO CÁO GỬI BÙ** — tool offline qua mốc {missed_at.strftime('%H:%M ngày %d/%m')}, "
                  f"gửi lại ngay khi khởi động.\n\n{report}")
    await client.send_message('me', report)
    await broadcast_to_bots(report)
    set_state('last_report_sent', datetime.datetime.now(VN_TZ).isoformat())

async def main():
    global MY_ID
    MY_ID = (await client.get_me()).id   # để lệnh điều khiển chỉ nhận trong Saved Messages

    scheduler = AsyncIOScheduler(timezone=VN_TZ)
    scheduler.add_job(auto_send_report, 'cron', hour=7, minute=0)
    scheduler.add_job(auto_send_report, 'cron', hour=16, minute=0)
    scheduler.add_job(backup_to_drive, 'cron', hour=11, minute=55)
    scheduler.add_job(backup_to_drive, 'cron', hour=23, minute=55)
    # Quét người đăng ký bot đích định kỳ (getUpdates) để bắt người mới /start
    scheduler.add_job(poll_subscribers_job, 'interval', minutes=2)
    scheduler.start()

    print("🚀 SIÊU MEGAZORD V6 ĐÃ LÊN NÒNG! VẮT KIỆT TÀI NGUYÊN BINANCE API TỚI GIỌT CUỐI CÙNG.")
    _bot_names = ', '.join(label for _, label in TARGET_BOT_TOKENS)  # in nhãn tên, KHÔNG lộ token
    print(f"   📡 Nguồn vào: {SOURCE_BOT} | 📤 Relay qua {len(TARGET_BOT_TOKENS)} bot tới subscriber của từng bot: {_bot_names}")
    backup_to_drive()
    await poll_subscribers_job()       # quét người đăng ký bot đích ngay lúc khởi động
    await catch_up_source_messages()   # đọc bù tin nhắn bị lỡ trong lúc tool tắt
    await catch_up_missed_report()     # lỡ mốc báo cáo 07:00/16:00 thì gửi bù ngay (đã gồm kèo vừa đọc bù)
    await client.run_until_disconnected()

if __name__ == '__main__':
    init_db()
    client.start()
    client.loop.run_until_complete(main())
