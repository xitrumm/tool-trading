# ==========================================
# KHỐI ML DÙNG CHUNG (V6 + ML)
# ==========================================
# File này là NGUỒN CHÂN LÝ DUY NHẤT cho: bộ feature, công thức trade plan,
# thuật toán gán nhãn (walk_label), lọc universe coin và DDL các bảng ML.
# Dùng chung bởi: bottrading.py (live), backfill_dataset.py (lịch sử),
# train_model.py (huấn luyện), ml_radar.py (radar) — để KHÔNG BAO GIỜ
# lệch nhau giữa lúc huấn luyện và lúc chạy thật (train/serve skew).
#
# CHỈ phụ thuộc pandas/numpy/pytz (đã có sẵn trong requirements) —
# KHÔNG import sklearn/telethon/requests, để bot chạy được chế độ
# thu thập dữ liệu (P0) mà không cần cài thêm gì.

import json
import datetime
import pandas as pd
import numpy as np
import pytz

VN_TZ = pytz.timezone('Asia/Ho_Chi_Minh')

# Cửa sổ tính feature = 100 nến, KHỚP limit=100 của BinanceRadar.get_klines —
# EMA seed trên cửa sổ ngắn bị lệch, nhưng lệch GIỐNG NHAU ở cả backfill lẫn live.
FEATURE_WINDOW = 100
# Bối cảnh BTC/ETH dùng 30 nến 1D — khớp limit=30 của check_market_weather.
MARKET_WINDOW = 30
# Horizon gán nhãn: 84 nến 4H = 14 ngày.
LABEL_HORIZON_CANDLES = 84
LABEL_SPEC = 'tp1_before_sl_14d_v1'

# 28 feature giá/volume — model v1 CHỈ train trên danh sách này.
# Các extras live (L/S, funding, OI, mention...) vẫn được log vào features_json
# nhưng predict_signal_prob chỉ lấy đúng các tên dưới đây → thêm key thừa vô hại.
PRICE_FEATURE_NAMES = [
    # Khung 4H (cửa sổ trailing 100 nến)
    'rsi14_4h', 'dist_ema7_4h', 'dist_ema25_4h', 'dist_ema99_4h', 'atr_pct_4h',
    'ret_1c_4h', 'ret_6c_4h', 'ret_42c_4h',
    'vol_ratio_last_vs20_4h', 'vol_ratio_24h_vs_7d_4h',
    'range_pos_20_4h', 'dist_swing_low20_4h',
    # Khung 1D
    'rsi14_1d', 'dist_ema7_1d', 'dist_ema25_1d', 'dist_ema99_1d',
    'ema_stack_1d', 'atr_pct_1d', 'ret_7d_1d', 'ret_30d_1d', 'days_above_ema25_1d',
    # Bối cảnh thị trường (BTC/ETH 1D, cửa sổ 30 nến)
    'btc_dist_ema25_1d', 'eth_dist_ema25_1d', 'btc_rsi14_1d', 'btc_ret_7d_1d',
    'weather_code', 'rel_strength_7d',
    # Hình học kèo
    'sl_pct',
]

# Cột chuẩn của response /api/v3/klines (giống bottrading.get_klines)
KLINE_COLUMNS = ['time', 'open', 'high', 'low', 'close', 'volume',
                 'close_time', 'qav', 'num_trades', 'tbbav', 'tbqav', 'ignore']

# Universe: loại stablecoin/fiat/wrapped — chỉ giữ coin đầu cơ được.
# (Leveraged token UP/DOWN đã bị Binance delist nên không cần rule suffix —
#  rule suffix dễ giết nhầm coin thật như JUP, SYRUP.)
STABLE_OR_FIAT_BASES = {
    'USDC', 'FDUSD', 'TUSD', 'DAI', 'USDP', 'BUSD', 'PYUSD', 'GUSD',
    'USDE', 'USD1', 'XUSD', 'BFUSD', 'USTC', 'UST',
    'EUR', 'EURI', 'AEUR', 'EURT', 'GBP', 'TRY', 'BRL', 'ARS', 'COP',
    'PLN', 'RON', 'UAH', 'ZAR', 'MXN', 'CZK', 'JPY',
}
WRAPPED_BASES = {'WBTC', 'WBETH', 'BETH', 'WETH', 'STETH', 'WSTETH', 'CBBTC', 'SOLVBTC'}

# DDL các bảng ML — bottrading.init_db và backfill_dataset cùng chạy list này.
ML_DDL = [
    '''CREATE TABLE IF NOT EXISTS ml_samples (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT NOT NULL,
        coin TEXT NOT NULL,
        source TEXT NOT NULL,
        features_json TEXT NOT NULL,
        entry REAL NOT NULL, sl REAL NOT NULL, tp1 REAL NOT NULL, tp2 REAL NOT NULL,
        rule_score REAL,
        ml_prob REAL, model_version TEXT,
        outcome INTEGER,
        outcome_detail TEXT,
        realized_r REAL, resolved_at TEXT
    )''',
    'CREATE UNIQUE INDEX IF NOT EXISTS idx_ml_samples_dedupe ON ml_samples(source, coin, ts)',
    'CREATE INDEX IF NOT EXISTS idx_ml_samples_pending ON ml_samples(outcome) WHERE outcome IS NULL',
    '''CREATE TABLE IF NOT EXISTS anomaly_alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT NOT NULL, coin TEXT NOT NULL,
        anomaly_score REAL NOT NULL, features_json TEXT NOT NULL
    )''',
    'CREATE INDEX IF NOT EXISTS idx_anomaly_coin_ts ON anomaly_alerts(coin, ts)',
]


# ==========================================
# TIỆN ÍCH CHUNG
# ==========================================
def to_float_frame(df):
    """Cast các cột số sang float. BẮT BUỘC vì get_klines của bot chỉ cast
    open/high/low/close — volume/qav vẫn là string sẽ làm sai mọi feature volume."""
    df = df.copy()
    for col in ('open', 'high', 'low', 'close', 'volume', 'qav'):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
    return df


def klines_to_df(raw):
    """Parse response thô của /api/v3/klines thành DataFrame đã cast số"""
    return to_float_frame(pd.DataFrame(raw, columns=KLINE_COLUMNS))


def vn_str_to_utc_ms(ts):
    """'YYYY-MM-DD HH:MM:SS' giờ VN → epoch milliseconds UTC (cho startTime của Binance)"""
    dt = VN_TZ.localize(datetime.datetime.strptime(ts, "%Y-%m-%d %H:%M:%S"))
    return int(dt.timestamp() * 1000)


def utc_ms_to_vn_str(ms):
    """Epoch milliseconds UTC → 'YYYY-MM-DD HH:MM:SS' giờ VN (format chuẩn của DB)"""
    dt = datetime.datetime.fromtimestamp(ms / 1000, tz=pytz.UTC).astimezone(VN_TZ)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def dumps_features(features):
    """Serialize dict feature → JSON; NaN/inf đổi thành null để JSON hợp lệ chuẩn"""
    clean = {}
    for k, v in features.items():
        if isinstance(v, (float, np.floating)):
            clean[k] = float(v) if np.isfinite(v) else None
        elif isinstance(v, (int, np.integer, bool)):
            clean[k] = int(v)
        else:
            clean[k] = v
    return json.dumps(clean, ensure_ascii=False)


def _finite(x):
    return x is not None and isinstance(x, (int, float, np.integer, np.floating)) and np.isfinite(x)


def _ema_last(close, period):
    return close.ewm(span=period, adjust=False).mean().iloc[-1]


def _ret(close, n):
    """Lợi nhuận n nến gần nhất; NaN nếu không đủ dữ liệu"""
    if len(close) <= n:
        return float('nan')
    base = close.iloc[-1 - n]
    return float(close.iloc[-1] / base - 1) if base else float('nan')


# ==========================================
# CHỈ BÁO — công thức Y HỆT bottrading.BinanceRadar
# ==========================================
def calculate_rsi(df, periods=14):
    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    avg_gain = gain.ewm(alpha=1 / periods, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / periods, adjust=False).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi.iloc[-1]


def calculate_atr(df, period=14):
    prev_close = df['close'].shift(1)
    tr = pd.concat([
        df['high'] - df['low'],
        (df['high'] - prev_close).abs(),
        (df['low'] - prev_close).abs()
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean().iloc[-1]


def build_trade_plan(df_4h, ema25_4h):
    """Tính Entry / Stoploss / TP1 / TP2 từ khung 4H — port NGUYÊN VĂN từ
    BinanceRadar.build_trade_plan để backfill và live ra đúng một con số.
    SL = min(swing low 20 nến, EMA25 4H) − 0.5 ATR, chặn tối đa -8% so với entry."""
    entry = df_4h['close'].iloc[-1]
    atr = calculate_atr(df_4h)
    swing_low = df_4h['low'].iloc[-20:].min()
    sl = min(swing_low, ema25_4h) - 0.5 * atr
    if sl <= 0 or (entry - sl) / entry > 0.08:
        sl = entry - 2 * atr
    if sl >= entry:  # ATR bất thường (coin mới list, dữ liệu lỗi)
        sl = entry * 0.95
    risk = entry - sl
    return {'entry': entry, 'sl': sl, 'tp1': entry + 1.5 * risk, 'tp2': entry + 3 * risk}


# ==========================================
# FEATURE BUILDER (28 feature giá/volume)
# ==========================================
def build_price_features(df_4h, df_1d, btc_df_1d=None, eth_df_1d=None, trade_plan=None):
    """Xây dict 28 feature từ nến — dòng CUỐI của df_4h/df_1d là nến quyết định.
    Live: truyền thẳng frame từ analyze_coin (100 nến, nến cuối đang chạy).
    Backfill: truyền slice kết thúc đúng tại nến quyết định (nến đã đóng).
    btc/eth: frame 1D cùng thời điểm (None/thiếu → feature bối cảnh = NaN).
    trade_plan: dict có entry/sl (None → tự tính từ df_4h).
    Thiếu dữ liệu ở đâu → NaN ở đó (model gradient boosting xử lý native)."""
    f = {name: float('nan') for name in PRICE_FEATURE_NAMES}

    df4 = to_float_frame(df_4h).tail(FEATURE_WINDOW).reset_index(drop=True)
    df1 = to_float_frame(df_1d).tail(FEATURE_WINDOW).reset_index(drop=True)
    if len(df4) < 2 or len(df1) < 2:
        return f

    # --- Khung 4H ---
    close4 = df4['close']
    last4 = float(close4.iloc[-1])
    try:
        f['rsi14_4h'] = float(calculate_rsi(df4))
        f['dist_ema7_4h'] = last4 / _ema_last(close4, 7) - 1
        f['dist_ema25_4h'] = last4 / _ema_last(close4, 25) - 1
        f['dist_ema99_4h'] = last4 / _ema_last(close4, 99) - 1
        f['atr_pct_4h'] = float(calculate_atr(df4)) / last4 if last4 else float('nan')
        f['ret_1c_4h'] = _ret(close4, 1)
        f['ret_6c_4h'] = _ret(close4, 6)
        f['ret_42c_4h'] = _ret(close4, 42)

        vol4 = df4['volume']
        if len(vol4) >= 21:
            base20 = vol4.iloc[-21:-1].mean()
            f['vol_ratio_last_vs20_4h'] = float(vol4.iloc[-1] / base20) if base20 else float('nan')
        if len(vol4) >= 42:
            base7d = vol4.iloc[-42:].mean()
            f['vol_ratio_24h_vs_7d_4h'] = float(vol4.iloc[-6:].mean() / base7d) if base7d else float('nan')

        if len(df4) >= 20:
            low20 = float(df4['low'].iloc[-20:].min())
            high20 = float(df4['high'].iloc[-20:].max())
            rng = high20 - low20
            f['range_pos_20_4h'] = (last4 - low20) / rng if rng > 0 else float('nan')
            f['dist_swing_low20_4h'] = last4 / low20 - 1 if low20 else float('nan')
    except Exception:
        pass

    # --- Khung 1D ---
    close1 = df1['close']
    last1 = float(close1.iloc[-1])
    try:
        f['rsi14_1d'] = float(calculate_rsi(df1))
        e7, e25, e99 = _ema_last(close1, 7), _ema_last(close1, 25), _ema_last(close1, 99)
        f['dist_ema7_1d'] = last1 / e7 - 1
        f['dist_ema25_1d'] = last1 / e25 - 1
        f['dist_ema99_1d'] = last1 / e99 - 1
        f['ema_stack_1d'] = float(last1 > e7 > e25 > e99)
        f['atr_pct_1d'] = float(calculate_atr(df1)) / last1 if last1 else float('nan')
        f['ret_7d_1d'] = _ret(close1, 7)
        f['ret_30d_1d'] = _ret(close1, 30)

        # Số ngày liên tiếp đóng cửa trên EMA25 (độ "tươi" của trend, cap 30)
        ema25_series = close1.ewm(span=25, adjust=False).mean()
        above = (close1 > ema25_series).to_numpy()
        days = 0
        for v in above[::-1]:
            if not v:
                break
            days += 1
        f['days_above_ema25_1d'] = float(min(days, 30))
    except Exception:
        pass

    # --- Bối cảnh thị trường (BTC/ETH, cửa sổ 30 nến khớp check_market_weather) ---
    try:
        btc_above = eth_above = None
        if btc_df_1d is not None and len(btc_df_1d) >= 2:
            btc = to_float_frame(btc_df_1d).tail(MARKET_WINDOW).reset_index(drop=True)
            btc_close = btc['close']
            btc_last = float(btc_close.iloc[-1])
            btc_e25 = _ema_last(btc_close, 25)
            f['btc_dist_ema25_1d'] = btc_last / btc_e25 - 1
            f['btc_rsi14_1d'] = float(calculate_rsi(btc))
            f['btc_ret_7d_1d'] = _ret(btc_close, 7)
            btc_above = btc_last > btc_e25
        if eth_df_1d is not None and len(eth_df_1d) >= 2:
            eth = to_float_frame(eth_df_1d).tail(MARKET_WINDOW).reset_index(drop=True)
            eth_close = eth['close']
            eth_last = float(eth_close.iloc[-1])
            eth_e25 = _ema_last(eth_close, 25)
            f['eth_dist_ema25_1d'] = eth_last / eth_e25 - 1
            eth_above = eth_last > eth_e25
        if btc_above is not None and eth_above is not None:
            # Cùng định nghĩa check_market_weather: 2=NẮNG ĐẸP, 0=BÃO TỐ, 1=BIẾN ĐỘNG
            f['weather_code'] = 2.0 if (btc_above and eth_above) else (0.0 if (not btc_above and not eth_above) else 1.0)
        if _finite(f['ret_7d_1d']) and _finite(f['btc_ret_7d_1d']):
            f['rel_strength_7d'] = f['ret_7d_1d'] - f['btc_ret_7d_1d']
    except Exception:
        pass

    # --- Hình học kèo ---
    try:
        plan = trade_plan if trade_plan else build_trade_plan(df4, _ema_last(close4, 25))
        entry, sl = float(plan['entry']), float(plan['sl'])
        f['sl_pct'] = (entry - sl) / entry if entry else float('nan')
    except Exception:
        pass

    return f


def rule_score_lite(f):
    """Phiên bản compute_score chỉ gồm các yếu tố TÁI LẬP ĐƯỢC từ lịch sử
    (không L/S, funding, mention) — làm baseline so sánh cho backfill.
    Live vẫn lưu compute_score đầy đủ vào cột rule_score."""
    score = 50.0
    rsi = f.get('rsi14_1d')
    if _finite(rsi):
        if 45 <= rsi <= 65:
            score += 10
        elif rsi > 75:
            score -= 10
    if f.get('ema_stack_1d') == 1:
        score += 10
    wc = f.get('weather_code')
    if wc == 2:
        score += 10
    elif wc == 0:
        score -= 15
    d25 = f.get('dist_ema25_1d')
    if _finite(d25) and d25 > 0.15:
        score -= 5
    return round(min(max(score, 0), 100))


# ==========================================
# GÁN NHÃN (walk_label) — dùng chung backfill & labeler live
# ==========================================
def walk_label(candles_after, entry, sl, tp1, tp2, horizon=LABEL_HORIZON_CANDLES):
    """Đi từng nến 4H SAU nến quyết định, chạm tính cả râu nến (như lệnh stop thật).
    Trả về dict {outcome, detail, realized_r, resolved_idx} hoặc None nếu CHƯA đủ
    dữ liệu kết luận (kèo live còn mới — labeler sẽ thử lại lần sau).

    Quy tắc (LABEL_SPEC = tp1_before_sl_14d_v1):
      - Cùng nến chạm cả SL lẫn TP1 (chưa từng chạm TP1) → 0, AMBIGUOUS_SL (bảo thủ)
      - SL trước  → 0, 'SL',  realized_r = -1.0
      - TP1 trước → 1, đi tiếp: chạm TP2 trước SL → 'TP2' r=3.0; ngược lại 'TP1' r=1.5
      - Hết horizon không chạm gì → 0, 'TIMEOUT', realized_r = mark-to-market
        (kèo đi ngang 14 ngày giam vốn = không thắng, nhưng giữ r để phân tích)"""
    entry, sl, tp1, tp2 = float(entry), float(sl), float(tp1), float(tp2)
    risk = entry - sl
    if risk <= 0 or candles_after is None or len(candles_after) == 0:
        return None

    df = to_float_frame(candles_after)
    highs = df['high'].to_numpy()[:horizon]
    lows = df['low'].to_numpy()[:horizon]
    closes = df['close'].to_numpy()[:horizon]

    tp1_hit = False
    for i in range(len(highs)):
        hi, lo = highs[i], lows[i]
        if not np.isfinite(hi) or not np.isfinite(lo):
            continue
        if not tp1_hit:
            hit_sl, hit_tp1 = lo <= sl, hi >= tp1
            if hit_sl and hit_tp1:
                return {'outcome': 0, 'detail': 'AMBIGUOUS_SL', 'realized_r': -1.0, 'resolved_idx': i}
            if hit_sl:
                return {'outcome': 0, 'detail': 'SL', 'realized_r': -1.0, 'resolved_idx': i}
            if hit_tp1:
                tp1_hit = True
                if hi >= tp2:  # nến khủng chạm luôn TP2 (SL đã loại ở nhánh trên)
                    return {'outcome': 1, 'detail': 'TP2', 'realized_r': 3.0, 'resolved_idx': i}
        else:
            hit_sl, hit_tp2 = lo <= sl, hi >= tp2
            if hit_tp2 and not hit_sl:
                return {'outcome': 1, 'detail': 'TP2', 'realized_r': 3.0, 'resolved_idx': i}
            if hit_sl:  # SL sau khi đã ăn TP1 (kể cả nến mơ hồ) → chốt mức TP1
                return {'outcome': 1, 'detail': 'TP1', 'realized_r': 1.5, 'resolved_idx': i}

    if len(highs) >= horizon:
        last_i = len(highs) - 1
        if tp1_hit:
            return {'outcome': 1, 'detail': 'TP1', 'realized_r': 1.5, 'resolved_idx': last_i}
        return {'outcome': 0, 'detail': 'TIMEOUT',
                'realized_r': float((closes[last_i] - entry) / risk), 'resolved_idx': last_i}
    return None  # chưa đủ nến trong horizon → còn chờ


# ==========================================
# LỌC UNIVERSE COIN (backfill + radar dùng chung)
# ==========================================
def filter_universe(tickers, top_n=150):
    """tickers: list dict từ /api/v3/ticker/24hr.
    Giữ cặp *USDT, loại stablecoin/fiat/wrapped, xếp theo quoteVolume giảm dần."""
    rows = []
    for t in tickers:
        sym = t.get('symbol', '')
        if not sym.endswith('USDT'):
            continue
        base = sym[:-4]
        if base in STABLE_OR_FIAT_BASES or base in WRAPPED_BASES:
            continue
        try:
            qv = float(t.get('quoteVolume', 0))
        except (TypeError, ValueError):
            qv = 0.0
        if qv <= 0:
            continue
        rows.append((sym, qv))
    rows.sort(key=lambda x: -x[1])
    return [s for s, _ in rows[:top_n]]
