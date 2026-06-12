# ==========================================
# BACKFILL DATASET — tạo dữ liệu huấn luyện từ lịch sử Binance
# ==========================================
# Chạy ngoài bot (offline, một lần): replay đúng bộ lọc EMA của bot trên
# nến quá khứ để tạo pseudo-signal, gán nhãn bằng diễn biến giá SAU đó
# (walk_label), ghi vào bảng ml_samples với source='backfill'.
#
# Cách dùng:
#   python backfill_dataset.py                          # full: top 150 coin, 540 ngày
#   python backfill_dataset.py --symbols BTC,ETH,SOL --days 90   # smoke test
#   python backfill_dataset.py --dry-run                # chỉ tính, không ghi DB
#
# Idempotent: chạy lại không tạo dòng trùng (INSERT OR IGNORE + unique index).
# KHÔNG import bottrading (file đó load config + Telethon ngay khi import).

import argparse
import datetime
import os
import sqlite3
import time

import numpy as np
import requests

import ml_features

SPOT_BASE = "https://api.binance.com/api/v3"
MS_4H = 4 * 3600 * 1000
MS_1D = 24 * 3600 * 1000
WARMUP_4H_MS = ml_features.FEATURE_WINDOW * MS_4H          # 100 nến 4H ≈ 17 ngày
LABEL_TAIL_MS = ml_features.LABEL_HORIZON_CANDLES * MS_4H  # 84 nến 4H = 14 ngày
REARM_MS = 7 * MS_1D  # sau khi phát 1 mẫu, coin phải chờ >= 7 ngày mới phát lại giữa trend

INSERT_COLUMNS = ('ts', 'coin', 'source', 'features_json', 'entry', 'sl', 'tp1', 'tp2',
                  'rule_score', 'outcome', 'outcome_detail', 'realized_r', 'resolved_at')


def fetch_json(url, sleep_ms, max_retries=4):
    """GET có retry: tôn trọng Retry-After khi dính 429/418, backoff lũy tiến khi lỗi mạng"""
    for attempt in range(max_retries):
        try:
            res = requests.get(url, timeout=20)
            if res.status_code in (429, 418):
                wait = int(res.headers.get('Retry-After', 30))
                print(f"   ⏳ Dính rate limit {res.status_code} — chờ {wait}s...")
                time.sleep(wait)
                continue
            res.raise_for_status()
            time.sleep(sleep_ms / 1000.0)
            return res.json()
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            time.sleep(2 ** attempt)
    return None


def fetch_klines_range(symbol, interval, start_ms, sleep_ms):
    """Kéo toàn bộ klines từ start_ms tới hiện tại (phân trang limit=1000)"""
    out, cur = [], start_ms
    while True:
        url = f"{SPOT_BASE}/klines?symbol={symbol}&interval={interval}&startTime={cur}&limit=1000"
        batch = fetch_json(url, sleep_ms)
        if not batch:
            break
        out.extend(batch)
        if len(batch) < 1000:
            break
        cur = batch[-1][0] + 1
    return ml_features.klines_to_df(out) if out else None


def resolve_symbols(args):
    """--symbols BTC,ETH → ['BTCUSDT','ETHUSDT']; mặc định top N theo quoteVolume"""
    if args.symbols:
        syms = []
        for s in args.symbols.split(','):
            s = s.strip().upper()
            if s:
                syms.append(s if s.endswith('USDT') else f"{s}USDT")
        return syms
    print(f"🌐 Lấy universe top {args.top} coin theo volume...")
    tickers = fetch_json(f"{SPOT_BASE}/ticker/24hr", args.sleep_ms)
    return ml_features.filter_universe(tickers, args.top)


def backfill_symbol(symbol, df_btc, df_eth, range_start_ms, now_ms, sleep_ms, min_gap_ms):
    """Replay bộ lọc trên 1 coin. Trả về list tuple sẵn sàng insert (khớp INSERT_COLUMNS)."""
    coin = symbol[:-4]
    fetch_start = range_start_ms - WARMUP_4H_MS - 5 * MS_1D  # đệm thêm vài ngày cho chắc
    df4 = fetch_klines_range(symbol, '4h', fetch_start, sleep_ms)
    df1 = fetch_klines_range(symbol, '1d', fetch_start - (ml_features.FEATURE_WINDOW + 5) * MS_1D, sleep_ms)
    if df4 is None or df1 is None or len(df4) < ml_features.FEATURE_WINDOW + 10:
        return []

    open4 = df4['time'].to_numpy(dtype=np.int64)
    open1 = df1['time'].to_numpy(dtype=np.int64)
    open_btc = df_btc['time'].to_numpy(dtype=np.int64) if df_btc is not None else None
    open_eth = df_eth['time'].to_numpy(dtype=np.int64) if df_eth is not None else None

    samples = []
    prev_pass = False
    last_emit_ms = -10 ** 18

    for j in range(len(df1)):
        t_open = int(open1[j])
        t_close = t_open + MS_1D  # khoảnh khắc nến 1D đóng (00:00 UTC hôm sau)
        if t_close > now_ms:
            break  # nến đang chạy — không phải nến quyết định
        if t_close < range_start_ms:
            continue  # ngoài khoảng --days yêu cầu

        # Slice 4H: mọi nến MỞ trước thời điểm quyết định → nến cuối đóng đúng tại t_close
        idx4 = int(np.searchsorted(open4, t_close))
        slice4 = df4.iloc[:idx4]
        if len(slice4) < ml_features.FEATURE_WINDOW:
            prev_pass = False
            continue
        # Chống look-ahead: nến cuối của slice phải đóng <= thời điểm quyết định
        assert int(slice4['close_time'].iloc[-1]) < t_close + 1, f"leak! {symbol} @ {t_close}"

        win4 = slice4.tail(ml_features.FEATURE_WINDOW)
        win1 = df1.iloc[:j + 1].tail(ml_features.FEATURE_WINDOW)

        # Bộ lọc Y HỆT analyze_coin: giá đóng 4H > EMA25(4H) VÀ giá đóng 1D > EMA25(1D)
        ema25_4h = win4['close'].ewm(span=25, adjust=False).mean().iloc[-1]
        ema25_1d = win1['close'].ewm(span=25, adjust=False).mean().iloc[-1]
        passed = (win4['close'].iloc[-1] > ema25_4h) and (win1['close'].iloc[-1] > ema25_1d)

        # Phát mẫu khi: filter MỚI pass (ngày breakout) hoặc đã pass liên tục >= 7 ngày
        # (re-sample giữa trend). min_gap chặn giai đoạn whipsaw lắc quanh EMA25
        # tạo cụm mẫu gần-trùng-nhau làm giảm tính độc lập của dataset.
        emit = (passed
                and (not prev_pass or (t_close - last_emit_ms) >= REARM_MS)
                and (t_close - last_emit_ms) >= min_gap_ms)
        prev_pass = passed
        if not emit:
            continue
        last_emit_ms = t_close

        # Trade plan + feature + nhãn — cùng một bộ hàm với đường live
        plan = ml_features.build_trade_plan(win4, ema25_4h)
        btc_slice = df_btc.iloc[:int(np.searchsorted(open_btc, t_close))] if open_btc is not None else None
        eth_slice = df_eth.iloc[:int(np.searchsorted(open_eth, t_close))] if open_eth is not None else None
        features = ml_features.build_price_features(win4, win1, btc_slice, eth_slice, plan)
        score = ml_features.rule_score_lite(features)

        candles_after = df4.iloc[idx4:]
        label = ml_features.walk_label(candles_after, plan['entry'], plan['sl'], plan['tp1'], plan['tp2'])
        if label is None:
            continue  # mẫu quá mới chưa phân thắng bại — bỏ, dataset backfill phải đủ nhãn

        resolved_ms = int(candles_after['close_time'].iloc[label['resolved_idx']])
        samples.append((
            ml_features.utc_ms_to_vn_str(t_close), coin, 'backfill',
            ml_features.dumps_features(features),
            float(plan['entry']), float(plan['sl']), float(plan['tp1']), float(plan['tp2']),
            float(score), int(label['outcome']), label['detail'],
            float(label['realized_r']), ml_features.utc_ms_to_vn_str(resolved_ms),
        ))
    return samples


def main():
    ap = argparse.ArgumentParser(description="Backfill dataset ML từ lịch sử Binance")
    ap.add_argument('--days', type=int, default=540, help='số ngày lịch sử (mặc định 540)')
    ap.add_argument('--top', type=int, default=150, help='top N coin theo volume (mặc định 150)')
    ap.add_argument('--symbols', type=str, default='', help='danh sách coin chỉ định, vd BTC,ETH,SOL')
    ap.add_argument('--sleep-ms', type=int, default=250, help='nghỉ giữa các request (mặc định 250ms)')
    ap.add_argument('--min-gap-days', type=int, default=2,
                    help='giãn cách tối thiểu giữa 2 mẫu cùng coin, kể cả ngày breakout (mặc định 2)')
    ap.add_argument('--db', type=str, default='trading_memory.db', help='file SQLite đích')
    ap.add_argument('--dry-run', action='store_true', help='chỉ tính toán, KHÔNG ghi DB')
    args = ap.parse_args()

    now_ms = int(time.time() * 1000)
    range_start_ms = now_ms - args.days * MS_1D
    symbols = resolve_symbols(args)
    print(f"🚀 Backfill {len(symbols)} coin | {args.days} ngày | DB: {args.db}"
          f"{' | DRY-RUN (không ghi)' if args.dry_run else ''}")

    # BTC/ETH 1D fetch MỘT lần cho mọi coin (bối cảnh thị trường)
    ctx_start = range_start_ms - (ml_features.MARKET_WINDOW + 5) * MS_1D
    df_btc = fetch_klines_range('BTCUSDT', '1d', ctx_start, args.sleep_ms)
    df_eth = fetch_klines_range('ETHUSDT', '1d', ctx_start, args.sleep_ms)

    conn = None
    if not args.dry_run:
        conn = sqlite3.connect(args.db)
        for stmt in ml_features.ML_DDL:
            conn.execute(stmt)
        conn.commit()

    total_new, total_computed, all_outcomes, all_details, all_r = 0, 0, [], {}, []
    t0 = time.time()
    for i, symbol in enumerate(symbols, 1):
        try:
            samples = backfill_symbol(symbol, df_btc, df_eth, range_start_ms, now_ms,
                                      args.sleep_ms, args.min_gap_days * MS_1D)
        except AssertionError:
            raise  # leak look-ahead là lỗi chí mạng — dừng ngay để sửa
        except Exception as e:
            print(f"   ⚠️ [{i}/{len(symbols)}] {symbol}: lỗi {e} — bỏ qua coin này")
            continue

        total_computed += len(samples)
        new_rows = 0
        if samples:
            all_outcomes.extend(s[9] for s in samples)
            all_r.extend(s[11] for s in samples)
            for s in samples:
                all_details[s[10]] = all_details.get(s[10], 0) + 1
            if conn:
                cur = conn.cursor()
                cur.executemany(
                    f"INSERT OR IGNORE INTO ml_samples ({', '.join(INSERT_COLUMNS)}) "
                    f"VALUES ({', '.join(['?'] * len(INSERT_COLUMNS))})", samples)
                new_rows = cur.rowcount
                conn.commit()
                total_new += max(new_rows, 0)
        win = (100 * sum(s[9] for s in samples) / len(samples)) if samples else 0
        print(f"   [{i}/{len(symbols)}] {symbol}: {len(samples)} mẫu"
              f"{f' ({new_rows} mới)' if conn else ''} | win {win:.0f}%")

    if conn:
        conn.close()

    print(f"\n{'=' * 60}")
    print(f"✅ XONG sau {(time.time() - t0) / 60:.1f} phút — {total_computed} mẫu tính được"
          + (f", {total_new} dòng MỚI ghi vào DB" if not args.dry_run else " (dry-run, không ghi)"))
    if all_outcomes:
        win_rate = 100 * sum(all_outcomes) / len(all_outcomes)
        print(f"   📊 Win rate (TP1 trước SL): {win_rate:.1f}%  (vùng hợp lý 30-50% cho mục tiêu 1.5R)")
        print(f"   📊 Phân bố kết quả: {all_details}")
        print(f"   📊 Realized R trung bình: {np.mean(all_r):+.3f}")
        amb = all_details.get('AMBIGUOUS_SL', 0)
        print(f"   📊 Tỷ lệ nến mơ hồ (AMBIGUOUS_SL): {100 * amb / len(all_outcomes):.1f}%")
        if not 25 <= win_rate <= 55:
            print("   ⚠️ Win rate ngoài vùng kỳ vọng — soát lại label/trade plan trước khi train!")


if __name__ == '__main__':
    main()
