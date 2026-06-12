# ==========================================
# ML RADAR — tự phát hiện coin có sóng bất thường (nguồn tín hiệu thứ 2)
# ==========================================
# Quét cross-section toàn bộ top coin USDT: coin nào "lạ so với phần còn lại
# NGAY LÚC NÀY" (volume/giá/biên độ) thì IsolationForest sẽ tự nổi lên —
# không cần persist model, mỗi lần quét fit lại trên chính lát cắt đó.
#
# Toàn bộ hàm ở đây ĐỒNG BỘ (requests) — bottrading LUÔN gọi qua
# asyncio.to_thread để không nghẽn event loop Telegram (quét mất ~45-60s).
# Thiếu sklearn → fallback rule z-score, radar vẫn chạy.

import time

import numpy as np
import pandas as pd
import requests

import ml_features

SPOT_BASE = "https://api.binance.com/api/v3"

# Guard cứng sau khi model flag: bot chỉ đánh BUY nên chỉ quan tâm
# pump có volume thật đỡ — không bắt dao rơi, không bắt coin bị xả.
MIN_VOL_RATIO = 3.0   # volume 24h phải gấp >= 3 lần trung bình 30 ngày
MIN_RET_1D = 0.0      # giá 24h phải dương


def _fetch_symbol_features(symbol, ticker):
    """1 request klines 1D limit=31 → dict 5 feature radar (None nếu thiếu dữ liệu)"""
    res = requests.get(f"{SPOT_BASE}/klines?symbol={symbol}&interval=1d&limit=31", timeout=15).json()
    if not isinstance(res, list) or len(res) < 15:
        return None
    df = ml_features.klines_to_df(res)
    closed = df.iloc[:-1]  # bỏ nến hôm nay đang chạy — baseline chỉ dùng nến đã đóng

    qav_hist = closed['qav'].tail(30)
    vol_mean, vol_std = float(qav_hist.mean()), float(qav_hist.std())
    ticker_qv = float(ticker.get('quoteVolume', 0))
    if vol_mean <= 0:
        return None

    rets_hist = closed['close'].pct_change().dropna().tail(30)
    ret_mean, ret_std = float(rets_hist.mean()), float(rets_hist.std())
    ret_1d = float(ticker.get('priceChangePercent', 0)) / 100.0

    atr = float(ml_features.calculate_atr(closed))
    day_range = float(ticker.get('highPrice', 0)) - float(ticker.get('lowPrice', 0))

    return {
        'vol_ratio_24h_30d': ticker_qv / vol_mean,
        'vol_z_30d': (ticker_qv - vol_mean) / vol_std if vol_std > 0 else 0.0,
        'ret_1d_pct': ret_1d,
        'ret_z_30d': (ret_1d - ret_mean) / ret_std if ret_std > 0 else 0.0,
        'range_expansion_atr': day_range / atr if atr > 0 else 0.0,
    }


RADAR_FEATURE_NAMES = ['vol_ratio_24h_30d', 'vol_z_30d', 'ret_1d_pct', 'ret_z_30d', 'range_expansion_atr']


def scan_anomalies(top_n=150, sleep_ms=100):
    """Quét 1 lượt toàn universe. Trả list dict alert (đã qua guard cứng),
    sắp theo anomaly_score giảm dần. Lỗi mạng coin nào bỏ qua coin đó."""
    tickers = requests.get(f"{SPOT_BASE}/ticker/24hr", timeout=20).json()
    ticker_map = {t['symbol']: t for t in tickers if isinstance(t, dict) and 'symbol' in t}
    symbols = ml_features.filter_universe(tickers, top_n)

    rows = []
    for sym in symbols:
        try:
            feats = _fetch_symbol_features(sym, ticker_map[sym])
            if feats:
                feats['symbol'] = sym
                rows.append(feats)
        except Exception:
            pass  # coin lỗi dữ liệu — bỏ, không làm hỏng cả lượt quét
        time.sleep(sleep_ms / 1000.0)

    if len(rows) < 30:  # cross-section quá mỏng thì so sánh "lạ so với đám đông" vô nghĩa
        return []

    matrix = pd.DataFrame(rows)
    X = matrix[RADAR_FEATURE_NAMES].to_numpy(dtype=float)
    X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)

    try:
        from sklearn.ensemble import IsolationForest
        iso = IsolationForest(n_estimators=200, contamination=0.03, random_state=42)
        pred = iso.fit_predict(X)
        scores = -iso.decision_function(X)  # càng cao càng bất thường
        flagged = pred == -1
    except ImportError:
        # Fallback không sklearn: rule z-score thuần
        flagged = (matrix['vol_z_30d'].to_numpy() > 4) & (matrix['ret_z_30d'].to_numpy() > 2.5)
        scores = matrix['vol_z_30d'].to_numpy(dtype=float)

    alerts = []
    for i, row in matrix.iterrows():
        if not flagged[i]:
            continue
        # Guard cứng: chỉ pump dương có volume thật
        if row['vol_ratio_24h_30d'] < MIN_VOL_RATIO or row['ret_1d_pct'] <= MIN_RET_1D:
            continue
        alerts.append({
            'coin': row['symbol'][:-4],  # 'PEPEUSDT' → 'PEPE' (khớp cột coin bảng signals)
            'symbol': row['symbol'],
            'anomaly_score': round(float(scores[i]), 4),
            'features': {k: round(float(row[k]), 4) for k in RADAR_FEATURE_NAMES},
        })
    alerts.sort(key=lambda a: -a['anomaly_score'])
    return alerts


def format_alert_message(alerts):
    """Soạn tin cảnh báo tiếng Việt cho Saved Messages / bot đích"""
    lines = [f"📡 **RADAR SOI COIN LẠ (ML)** — {len(alerts)} mã bất thường:"]
    for a in alerts:
        ft = a['features']
        lines.append(
            f"🔥 **{a['coin']}** — volume 24h gấp {ft['vol_ratio_24h_30d']:.1f} lần TB 30 ngày"
            f" | giá 24h {ft['ret_1d_pct'] * 100:+.1f}% | biên độ {ft['range_expansion_atr']:.1f}×ATR"
        )
        lines.append(
            f"   Điểm bất thường: {a['anomaly_score']:.2f}"
            f" | Đã tính 1 lượt nhắc (RAW_RADAR) — cần nguồn khác xác nhận cùng ngày"
        )
    return "\n".join(lines)
