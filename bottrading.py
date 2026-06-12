import sqlite3
import re
import datetime
import json
import time
import requests
import pandas as pd
import numpy as np
import os
import shutil
import asyncio
from telethon import TelegramClient, events
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import pytz

# --- Khối ML (SHADOW MODE) ---
# ml_features chỉ cần pandas/numpy (đã có sẵn) — luôn import được.
# ml_predict/ml_radar có thể cần sklearn/joblib — thiếu thì bot vẫn chạy Y HỆT bản cũ.
import ml_features
try:
    import ml_predict
    HAS_ML_PREDICT = True
except Exception:
    HAS_ML_PREDICT = False
try:
    import ml_radar
    HAS_ML_RADAR = True
except Exception:
    HAS_ML_RADAR = False

# True = cảnh báo radar cũng broadcast tới bot đích; mặc định chỉ gửi Saved Messages
RADAR_NOTIFY_TARGETS = False

VN_TZ = pytz.timezone('Asia/Ho_Chi_Minh')  # mọi mốc thời gian của tool tính theo giờ Việt Nam

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
    """Đọc target_bots.txt — mỗi dòng 1 bot đích (@username hoặc ID số), hỗ trợ comment #"""
    if not os.path.exists(TARGET_BOTS_FILE):
        raise SystemExit(f"❌ Không tìm thấy {TARGET_BOTS_FILE} — tạo file, mỗi dòng 1 bot đích")
    with open(TARGET_BOTS_FILE, 'r', encoding='utf-8-sig') as f:
        bots = [_parse_entity(line) for line in f if line.strip() and not line.strip().startswith('#')]
    if not bots:
        raise SystemExit(f"❌ {TARGET_BOTS_FILE} đang rỗng — thêm ít nhất 1 bot đích (@username hoặc ID số)")
    return bots

_cfg = load_config()
API_ID = int(_cfg['API_ID'])                    # Dãy số ID từ my.telegram.org
API_HASH = _cfg['API_HASH']                     # Chuỗi Hash từ my.telegram.org
SOURCE_BOT = _parse_entity(_cfg['SOURCE_BOT'])  # Bot nguồn: chỉ đọc tin nhắn từ bot này
TARGET_BOTS = load_target_bots()                # Bot đích: nhận kèo chốt + báo cáo

client = TelegramClient('megazord_session', API_ID, API_HASH)

async def broadcast_to_bots(message):
    """Gửi 1 tin nhắn tới tất cả bot đích (giãn 1 giây/bot để tránh FloodWait)"""
    for bot in TARGET_BOTS:
        try:
            await client.send_message(bot, message)
            await asyncio.sleep(1)
        except Exception as e:
            print(f"   ⚠️ Không gửi được tới {bot}: {e}")

# ==========================================
# 2. KHỐI VỆ TINH BINANCE (QUANT ENGINE V6)
# ==========================================
class BinanceRadar:
    def __init__(self):
        self.base_url = "https://api.binance.com/api/v3"
        self.fapi_url = "https://fapi.binance.com/fapi/v1"
        self.data_url = "https://fapi.binance.com/futures/data"
        # Cache frame BTC/ETH của lần check_market_weather gần nhất — feature ML dùng lại, 0 call thêm
        self.last_btc_df = None
        self.last_eth_df = None

    def get_klines(self, symbol, interval, limit=100):
        url = f"{self.base_url}/klines?symbol={symbol}&interval={interval}&limit={limit}"
        res = requests.get(url).json()
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
        chặn tối đa -8% so với entry. TP theo R:R 1.5 và 3.0.
        Công thức nằm trong ml_features (dùng chung với backfill ML để
        train/serve không lệch nhau) — hành vi Y HỆT bản cũ."""
        return ml_features.build_trade_plan(df_4h, ema25_4h)

    def check_market_weather(self):
        """Kiểm tra cả 2 anh cả: BTC và ETH"""
        try:
            btc_df = self.get_klines("BTCUSDT", "1d", 30)
            eth_df = self.get_klines("ETHUSDT", "1d", 30)
            self.last_btc_df, self.last_eth_df = btc_df, eth_df  # cache cho feature ML

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
            ls_ratio = float(requests.get(url_ls).json()[0]['longShortRatio'])

            # Funding Rate (Nhân 100 để ra % luôn cho dễ nhìn)
            url_fr = f"{self.fapi_url}/premiumIndex?symbol={symbol}"
            funding_rate = float(requests.get(url_fr).json()['lastFundingRate']) * 100

            # Open Interest (OI)
            url_oi = f"{self.fapi_url}/openInterest?symbol={symbol}"
            oi = float(requests.get(url_oi).json()['openInterest'])

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
            tech_data['_df_4h'], tech_data['_df_1d'] = df_4h, df_1d  # frame thô cho feature ML (không refetch)
            return tech_data
        except: return None

radar = BinanceRadar()

# ==========================================
# 3. KHỐI LƯU TRỮ & ĐỒNG BỘ CLOUD (GIỮ NGUYÊN)
# ==========================================
def init_db():
    conn = sqlite3.connect('trading_memory.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS signals (date TEXT, coin TEXT, timeframe TEXT, type TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS money_flow (date TEXT, sector_from TEXT, sector_to TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS bot_state (key TEXT PRIMARY KEY, value TEXT)''')
    # Migrate DB cũ: thêm cột điểm + trade plan cho bảng signals (đã có thì bỏ qua)
    for col in ('score REAL', 'entry REAL', 'stoploss REAL', 'tp1 REAL', 'tp2 REAL'):
        try: c.execute(f'ALTER TABLE signals ADD COLUMN {col}')
        except sqlite3.OperationalError: pass
    # Bảng ML (shadow mode): mẫu kèo chờ chấm kết quả + cảnh báo radar
    for stmt in ml_features.ML_DDL:
        c.execute(stmt)
    conn.commit()
    conn.close()

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
            report += f"\n**🛡️ ĐÃ CHẶN KÈO RÁC (HÔM NAY):**\n"
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
    return (f"📥 Entry: {fmt_price(entry)}\n"
            f"🛑 Stoploss: {fmt_price(sl)} ({(sl/entry - 1)*100:.1f}%)\n"
            f"🎯 TP1: {fmt_price(tp1)} (+{(tp1/entry - 1)*100:.1f}%) | TP2: {fmt_price(tp2)} (+{(tp2/entry - 1)*100:.1f}%)")

async def check_and_evaluate(coin, now, force_urgent=False, source=""):
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
            if not tech: return

            # In Log siêu chi tiết như 1 Quant Trader thực thụ
            print(f"   📊 [Kỹ thuật] Giá: {tech['price']:.4f} | EMA(7/25/99): ({tech['ema7']:.4f} / {tech['ema25']:.4f} / {tech['ema99']:.4f}) | RSI: {tech['rsi']:.2f}")

            if not tech['pass_ema']:
                print(f"   ❌ Loại {coin}: Cấu trúc giá yếu (Dưới EMA25 4H/1D)")
                insert_db('signals', (now, coin, "4h_1d_check", "XIT_KY_THUAT"),
                          columns=('date', 'coin', 'timeframe', 'type'))
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
            label = f"🌟 KÈO VIP: {coin}" if is_vip else f"✅ KÈO THƯỜNG: {coin}"
            print(f"   {'🌟 CHỐT KÈO VIP' if is_vip else '✅ CHỐT KÈO THƯỜNG'} {coin} | 💯 Điểm: {score}/100 (hạng {rank} hôm nay)"
                  + (" | 🏆 TOP PICK" if is_top else ""))

            insert_db('signals', (now, coin, stats_info, sig_type, score, tech['entry'], tech['sl'], tech['tp1'], tech['tp2']),
                      columns=('date', 'coin', 'timeframe', 'type', 'score', 'entry', 'stoploss', 'tp1', 'tp2'))

            # --- BƯỚC 3.5: ML SHADOW MODE (chỉ quan sát — KHÔNG can thiệp kèo) ---
            # Log đủ feature + dự đoán để sau này so ML với kết quả thật.
            # Lỗi ở đây tuyệt đối không được chặn việc phát kèo → bọc try/except.
            ml_line = ""
            try:
                features = ml_features.build_price_features(
                    tech['_df_4h'], tech['_df_1d'],
                    btc_df_1d=radar.last_btc_df, eth_df_1d=radar.last_eth_df,
                    trade_plan=tech)
                # Extras chỉ live mới có (backfill không tái lập được) — nhiên liệu cho model v2
                features.update({
                    'ls_ratio_top': ls_ratio, 'funding_rate_pct': fr, 'open_interest': oi,
                    'mention_count_today': total_mentions,
                    'is_urgent_source': int(force_urgent), 'is_vip_rule': int(is_vip),
                    'rule_score_full': float(score),
                })
                ml_prob, ml_version = (ml_predict.predict_signal_prob(features)
                                       if HAS_ML_PREDICT else (None, None))
                insert_db('ml_samples',
                          (now, coin, 'live', ml_features.dumps_features(features),
                           tech['entry'], tech['sl'], tech['tp1'], tech['tp2'],
                           float(score), ml_prob, ml_version),
                          columns=('ts', 'coin', 'source', 'features_json', 'entry', 'sl',
                                   'tp1', 'tp2', 'rule_score', 'ml_prob', 'model_version'))
                if ml_prob is not None:
                    ml_line = f"\n🤖 ML: {ml_prob * 100:.0f}% khả năng chạm TP1 trước SL"
                    print(f"   🤖 [ML Shadow] {coin}: {ml_prob * 100:.0f}% (model {ml_version})")
            except Exception as e:
                print(f"   ⚠️ Khối ML shadow lỗi (bỏ qua, kèo vẫn phát bình thường): {e}")

            msg = (f"{label}\n"
                   f"💯 Điểm đáng giá: {score}/100 (hạng {rank} hôm nay){ml_line}\n"
                   f"{format_trade_plan(tech)}\n"
                   f"{stats_info}\n"
                   f"Thị trường: {weather} | OI: {oi:,.0f}")
            if is_top:
                msg = f"🏆🏆🏆 TOP PICK — KÈO ĐÁNG GIÁ NHẤT HÔM NAY 🏆🏆🏆\n{msg}"
            await broadcast_to_bots(msg)

    except Exception as e: print("Lỗi soi chéo:", e)

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
                file_path = await message.download_media(file='temp_data.xlsx')
                try:
                    df = pd.read_excel(file_path) if 'excel' in mime_type or 'spreadsheetml' in mime_type else pd.read_csv(file_path)
                    df.columns = [str(c).strip().upper() for c in df.columns]
                    score_col = next((c for c in df.columns if 'PRIORITY' in c or 'SCORE' in c), None)
                    coin_col = next((c for c in df.columns if 'SYMBOL' in c or 'COIN' in c), None)
                    if score_col and coin_col:
                        df[score_col] = pd.to_numeric(df[score_col], errors='coerce')
                        top_coins = df[df[score_col] > 70]
                        if not top_coins.empty:
                            for _, row in top_coins.iterrows():
                                raw_coin = str(row[coin_col]).upper().replace('/USDT', '').strip()
                                insert_db('signals', (now, raw_coin, "excel", "RAW_EXCEL"),
                                          columns=('date', 'coin', 'timeframe', 'type'))
                                await check_and_evaluate(raw_coin, now, force_urgent=True, source=f"EXCEL_SCORE_{row[score_col]}")
                except Exception as e: pass
                finally:
                    if os.path.exists(file_path): os.remove(file_path)
                return

        if not text: return

        if "Watchlist" in text and "Mới thêm" in text:
            urgent_coins = re.findall(r'•\s*(.*?)\s*[—\-]', text)
            for coin in urgent_coins:
                coin = coin.strip().upper()
                insert_db('signals', (now, coin, "watchlist", "RAW_URGENT"),
                          columns=('date', 'coin', 'timeframe', 'type'))
                await check_and_evaluate(coin, now, force_urgent=True, source="WATCHLIST ĐỘT BIẾN")

        flow_match = re.search(r'([A-Z0-9]+)\s*→\s*([A-Z0-9]+)', text)
        if flow_match:
            coin_from = flow_match.group(1).upper()
            coin_to = flow_match.group(2).upper()
            insert_db('money_flow', (now, coin_from, coin_to))
            await check_and_evaluate(coin_to, now)

        sig_match = re.search(r'symbol:\s*([A-Z0-9]+)/USDT\s*\|\s*direction:\s*(BUY|SELL)\s*\|\s*timeframe:\s*([0-9a-z]+)', text, re.IGNORECASE)
        if sig_match:
            coin = sig_match.group(1).upper()
            direction = sig_match.group(2).upper()
            timeframe = sig_match.group(3).lower()
            if direction == 'BUY':
                insert_db('signals', (now, coin, timeframe, "RAW_SIGNAL"),
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
    """Lệnh điều khiển — gõ từ chính tài khoản của bạn, ở bất kỳ chat nào"""
    try:
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
        elif text == '/ml':
            await event.reply(build_ml_status())
        elif text == '/radar':
            await event.reply("📡 Đang quét radar coin bất thường (~1 phút, bot vẫn nghe tin bình thường)...")
            result = await radar_scan_job(notify=False)
            await event.reply(result)
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

            for bot in TARGET_BOTS:
                try:
                    await client.send_message(bot, "🧪 TIN TEST từ Siêu Megazord V6 — kênh gửi hoạt động tốt!")
                    results.append(f"✅ Gửi tới {bot}: OK")
                    await asyncio.sleep(1)
                except Exception as e:
                    results.append(f"❌ Gửi tới {bot}: {e} (đã bấm /start với bot này chưa?)")

            results.append(f"\n📡 Nguồn đang nghe: {SOURCE_BOT}")
            await event.reply("🧪 **KẾT QUẢ TỰ KIỂM TRA:**\n" + "\n".join(results))
    except Exception as e: pass

# ==========================================
# 5.5. KHỐI ML SHADOW (gán nhãn kết quả + radar coin lạ + báo cáo /ml)
# ==========================================
def _label_worker(rows):
    """Worker ĐỒNG BỘ (chạy trong thread riêng qua asyncio.to_thread):
    fetch nến 4H sau thời điểm vào kèo rồi chấm TP1-trước-hay-SL-trước.
    rows: list (id, ts, coin, entry, sl, tp1, tp2). Trả list (id, label|None, expired)."""
    out = []
    now_utc_ms = int(datetime.datetime.now(pytz.UTC).timestamp() * 1000)
    expire_ms = ml_features.LABEL_HORIZON_CANDLES * 4 * 3600 * 1000 + 7 * 86400000
    for row_id, ts, coin, entry, sl, tp1, tp2 in rows:
        try:
            start_ms = ml_features.vn_str_to_utc_ms(ts)
            res = requests.get(
                f"https://api.binance.com/api/v3/klines?symbol={coin}USDT&interval=4h"
                f"&startTime={start_ms}&limit={ml_features.LABEL_HORIZON_CANDLES + 6}", timeout=15).json()
            candles = ml_features.klines_to_df(res) if isinstance(res, list) and res else None
            if candles is not None:
                # Chỉ chấm trên nến ĐÃ ĐÓNG — nến đang chạy còn quét thêm râu, chấm sớm dễ sai
                candles = candles[candles['close_time'] < now_utc_ms]
            if candles is None or len(candles) == 0:
                # Không có dữ liệu (coin delist?) — quá hạn thì khoanh vùng bỏ, không retry mãi
                out.append((row_id, None, (now_utc_ms - start_ms) > expire_ms))
            else:
                label = ml_features.walk_label(candles, entry, sl, tp1, tp2)
                if label:
                    label['resolved_at'] = ml_features.utc_ms_to_vn_str(
                        int(candles['close_time'].iloc[label['resolved_idx']]))
                out.append((row_id, label, False))
        except Exception as e:
            print(f"   ⚠️ Label {coin}: {e}")
            out.append((row_id, None, False))
        time.sleep(0.2)  # giãn request tránh rate limit
    return out

async def label_pending_samples_job():
    """Chấm kết quả các kèo live đang chờ trong ml_samples — chạy 6h/lần theo lịch"""
    try:
        init_db()
        conn = sqlite3.connect('trading_memory.db')
        cutoff = (datetime.datetime.now(VN_TZ) - datetime.timedelta(hours=4)).strftime("%Y-%m-%d %H:%M:%S")
        rows = conn.execute(
            "SELECT id, ts, coin, entry, sl, tp1, tp2 FROM ml_samples "
            "WHERE outcome IS NULL AND outcome_detail IS NULL AND source='live' AND ts <= ? "
            "ORDER BY ts LIMIT 100", (cutoff,)).fetchall()
        conn.close()
        if rows:
            results = await asyncio.to_thread(_label_worker, rows)
            conn = sqlite3.connect('trading_memory.db')
            now_str = datetime.datetime.now(VN_TZ).strftime("%Y-%m-%d %H:%M:%S")
            resolved = 0
            for row_id, label, expired in results:
                if label:
                    conn.execute(
                        "UPDATE ml_samples SET outcome=?, outcome_detail=?, realized_r=?, resolved_at=? WHERE id=?",
                        (label['outcome'], label['detail'], label['realized_r'], label['resolved_at'], row_id))
                    resolved += 1
                elif expired:
                    conn.execute("UPDATE ml_samples SET outcome_detail='EXPIRED_NO_DATA', resolved_at=? WHERE id=?",
                                 (now_str, row_id))
            conn.commit()
            conn.close()
            if resolved:
                print(f"\n🏷️ ML labeler: chấm xong {resolved}/{len(rows)} kèo chờ kết quả.")
        set_state('last_label_run', datetime.datetime.now(VN_TZ).isoformat())
    except Exception as e:
        print(f"⚠️ Lỗi job gán nhãn ML: {e}")

async def radar_scan_job(notify=True):
    """Quét radar coin bất thường (4h/lần theo lịch, hoặc gõ /radar).
    Coin lạ chỉ được TÍNH 1 LƯỢT NHẮC (RAW_RADAR) — không bao giờ tự chốt kèo một mình.
    Trả chuỗi tóm tắt để lệnh /radar in ra."""
    if not HAS_ML_RADAR:
        return "⚠️ Radar chưa sẵn sàng (thiếu module ml_radar)."
    try:
        now_vn = datetime.datetime.now(VN_TZ)
        now_str = now_vn.strftime("%Y-%m-%d %H:%M:%S")
        alerts = await asyncio.to_thread(ml_radar.scan_anomalies)  # ~1 phút, chạy thread riêng không nghẽn bot
        set_state('last_radar_scan', now_vn.isoformat())

        # Dedupe: coin đã cảnh báo trong 24h thì không báo lại
        init_db()
        conn = sqlite3.connect('trading_memory.db')
        cutoff = (now_vn - datetime.timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
        new_alerts = [a for a in alerts if conn.execute(
            "SELECT COUNT(*) FROM anomaly_alerts WHERE coin=? AND ts > ?",
            (a['coin'], cutoff)).fetchone()[0] == 0]
        conn.close()

        if not new_alerts:
            return (f"📡 Radar quét xong: {len(alerts)} mã flag nhưng đều đã cảnh báo trong 24h."
                    if alerts else "📡 Radar quét xong: thị trường không có gì lạ.")

        for a in new_alerts:
            insert_db('anomaly_alerts', (now_str, a['coin'], a['anomaly_score'], json.dumps(a['features'])),
                      columns=('ts', 'coin', 'anomaly_score', 'features_json'))
            insert_db('signals', (now_str, a['coin'], 'radar', 'RAW_RADAR'),
                      columns=('date', 'coin', 'timeframe', 'type'))

        msg = ml_radar.format_alert_message(new_alerts)
        print(f"\n[{now_str}] 📡 RADAR: {len(new_alerts)} coin bất thường mới: "
              + ", ".join(a['coin'] for a in new_alerts))
        if notify:
            await client.send_message('me', msg)
            if RADAR_NOTIFY_TARGETS:
                await broadcast_to_bots(msg)
        # Cho từng coin đi qua đúng pipeline gác cổng (KHÔNG force_urgent —
        # cần nguồn khác nhắc cùng ngày mới đủ 2 lượt để kích hoạt phân tích sâu)
        for a in new_alerts:
            await check_and_evaluate(a['coin'], now_str)
        return msg
    except Exception as e:
        print(f"⚠️ Lỗi radar scan: {e}")
        return f"⚠️ Radar lỗi: {e}"

def build_ml_status():
    """Tổng hợp trạng thái ML cho lệnh /ml"""
    lines = ["🤖 **TRẠNG THÁI ML (SHADOW MODE)**"]
    info = ml_predict.get_model_info() if HAS_ML_PREDICT else None
    if info:
        m = info.get('metrics', {})
        lines.append(f"📦 Model: {info['version']} | train {info.get('n_train')} mẫu"
                     f" | AUC {m.get('walk_forward_auc')} (rule baseline {m.get('rule_baseline_auc')})")
    else:
        lines.append("📦 Model: CHƯA CÓ — đang thu thập dữ liệu."
                     " Chạy backfill_dataset.py + train_model.py rồi restart bot.")
    try:
        init_db()
        conn = sqlite3.connect('trading_memory.db')
        for src in ('live', 'backfill'):
            total, labeled, wins = conn.execute(
                "SELECT COUNT(*), COUNT(outcome), COALESCE(SUM(outcome),0) FROM ml_samples WHERE source=?",
                (src,)).fetchone()
            if total:
                wr = f" | win {100 * wins / labeled:.0f}%" if labeled else ""
                lines.append(f"🗃️ Mẫu {src}: {total}, đã có kết quả {labeled}{wr}")
        pending = conn.execute("SELECT COUNT(*) FROM ml_samples WHERE outcome IS NULL"
                               " AND outcome_detail IS NULL AND source='live'").fetchone()[0]
        n_alerts = conn.execute("SELECT COUNT(*) FROM anomaly_alerts").fetchone()[0]
        conn.close()
        lines.append(f"⏳ Kèo live chờ chấm kết quả: {pending}")
        lines.append(f"📡 Radar đã cảnh báo: {n_alerts} lượt")
    except Exception as e:
        lines.append(f"⚠️ Lỗi đọc DB: {e}")
    lines.append(f"🏷️ Label job gần nhất: {get_state('last_label_run') or 'chưa chạy'}")
    lines.append(f"📡 Radar quét gần nhất: {get_state('last_radar_scan') or 'chưa chạy'}")
    return "\n".join(lines)

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
    scheduler = AsyncIOScheduler(timezone=VN_TZ)
    scheduler.add_job(auto_send_report, 'cron', hour=7, minute=0)
    scheduler.add_job(auto_send_report, 'cron', hour=16, minute=0)
    scheduler.add_job(backup_to_drive, 'cron', hour=11, minute=55)
    scheduler.add_job(backup_to_drive, 'cron', hour=23, minute=55)
    # Job ML: chấm kết quả kèo 6h/lần; radar quét ngay sau mỗi nến 4H đóng (giờ VN)
    scheduler.add_job(label_pending_samples_job, 'cron', hour='1,7,13,19', minute=20)
    scheduler.add_job(radar_scan_job, 'cron', hour='3,7,11,15,19,23', minute=10)
    scheduler.start()

    print("🚀 SIÊU MEGAZORD V6 ĐÃ LÊN NÒNG! VẮT KIỆT TÀI NGUYÊN BINANCE API TỚI GIỌT CUỐI CÙNG.")
    print(f"   📡 Nguồn vào: {SOURCE_BOT} | 📤 Bot đích ({len(TARGET_BOTS)}): {', '.join(str(b) for b in TARGET_BOTS)}")
    ml_info = ml_predict.get_model_info() if HAS_ML_PREDICT else None
    if ml_info:
        print(f"   🤖 ML shadow: model {ml_info['version']}"
              f" (AUC {ml_info.get('metrics', {}).get('walk_forward_auc')}) — chấm xác suất song song, không can thiệp kèo")
    else:
        print("   🤖 ML shadow: chưa có model — chế độ THU THẬP DỮ LIỆU (kèo vẫn được log feature + chấm kết quả)")
    backup_to_drive()
    await catch_up_source_messages()   # đọc bù tin nhắn bị lỡ trong lúc tool tắt
    await catch_up_missed_report()     # lỡ mốc báo cáo 07:00/16:00 thì gửi bù ngay (đã gồm kèo vừa đọc bù)
    await client.run_until_disconnected()

if __name__ == '__main__':
    init_db()
    client.start()
    client.loop.run_until_complete(main())
