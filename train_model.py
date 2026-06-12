# ==========================================
# TRAIN MODEL — huấn luyện model chấm xác suất kèo (chạy offline)
# ==========================================
# Đọc ml_samples đã có nhãn → đánh giá purged walk-forward (KHÔNG BAO GIỜ
# shuffle split — nhãn nhìn 14 ngày tương lai, shuffle là tự lừa mình) →
# train model cuối + calibrate xác suất → ghi models/signal_model.pkl.
#
# Cách dùng:
#   python train_model.py                      # train trên backfill (mặc định)
#   python train_model.py --source backfill,live --min-rows 500
#   python train_model.py --force              # bỏ qua ngưỡng ship (chỉ để thử nghiệm)
#
# Ngưỡng ship: mean AUC >= 0.56 VÀ hơn baseline rule >= +0.02 VÀ calibration
# đơn điệu thô — dưới ngưỡng exit code 1, KHÔNG ghi model (trừ khi --force).

import argparse
import datetime
import json
import os
import sqlite3
import sys

import numpy as np
import pandas as pd

import ml_features

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_OUT = os.path.join(BASE_DIR, 'models', 'signal_model.pkl')

SHIP_MIN_AUC = 0.56
SHIP_MIN_EDGE_VS_RULE = 0.02
EMBARGO_DAYS = 14  # = horizon nhãn: mẫu train sát mép validation bị "nhìn xuyên" tương lai → bỏ
N_CHUNKS = 6


def load_dataset(db, sources):
    conn = sqlite3.connect(db)
    q = (f"SELECT ts, coin, features_json, rule_score, outcome FROM ml_samples "
         f"WHERE outcome IS NOT NULL AND source IN ({','.join(['?'] * len(sources))}) ORDER BY ts")
    rows = conn.execute(q, sources).fetchall()
    conn.close()
    if not rows:
        return None
    feats = pd.DataFrame([json.loads(r[2]) for r in rows])
    X = feats.reindex(columns=ml_features.PRICE_FEATURE_NAMES).astype(float)
    return {
        'X': X,
        'y': np.array([r[4] for r in rows], dtype=int),
        'rule': np.array([r[3] if r[3] is not None else 50.0 for r in rows], dtype=float),
        'ts': pd.to_datetime([r[0] for r in rows]),
        'coin': [r[1] for r in rows],
    }


def make_models():
    """2 ứng viên: LR baseline (cần imputer+scaler) và HistGB (ăn NaN native).
    Hàm factory — mỗi fold tạo model MỚI, không tái dùng model đã fit."""
    from sklearn.pipeline import Pipeline
    from sklearn.impute import SimpleImputer
    from sklearn.preprocessing import StandardScaler
    from sklearn.linear_model import LogisticRegression
    from sklearn.ensemble import HistGradientBoostingClassifier
    return {
        'logistic': lambda: Pipeline([
            ('imputer', SimpleImputer(strategy='median')),
            ('scaler', StandardScaler()),
            ('lr', LogisticRegression(max_iter=1000, C=1.0)),
        ]),
        'hist_gb': lambda: HistGradientBoostingClassifier(
            max_iter=300, early_stopping=True, max_leaf_nodes=31,
            learning_rate=0.06, min_samples_leaf=50, l2_regularization=1.0,
            random_state=42),
    }


def precision_at(y_true, prob, frac):
    k = max(1, int(len(prob) * frac))
    top = np.argsort(-prob)[:k]
    return float(np.mean(y_true[top]))


def walk_forward_folds(ts, n_chunks=N_CHUNKS, embargo_days=EMBARGO_DAYS):
    """Chia timeline thành n chunk đều nhau; fold i: train = mọi mẫu TRƯỚC chunk
    validation trừ vùng embargo 14 ngày sát mép (purged walk-forward)."""
    n = len(ts)
    chunk = n // n_chunks
    folds = []
    for i in range(1, n_chunks):
        v_start = i * chunk
        v_end = (i + 1) * chunk if i < n_chunks - 1 else n
        cut = ts[v_start] - pd.Timedelta(days=embargo_days)
        train_idx = np.where((np.arange(n) < v_start) & np.asarray(ts < cut))[0]
        val_idx = np.arange(v_start, v_end)
        if len(train_idx) >= 100 and len(val_idx) >= 50:
            folds.append((train_idx, val_idx))
    return folds


def main():
    ap = argparse.ArgumentParser(description="Train model chấm xác suất kèo")
    ap.add_argument('--db', type=str, default=os.path.join(BASE_DIR, 'trading_memory.db'))
    ap.add_argument('--source', type=str, default='backfill', help='backfill | live | backfill,live')
    ap.add_argument('--min-rows', type=int, default=300)
    ap.add_argument('--out', type=str, default=DEFAULT_OUT)
    ap.add_argument('--force', action='store_true', help='ghi model kể cả khi rớt ngưỡng ship')
    args = ap.parse_args()

    from sklearn.metrics import roc_auc_score, brier_score_loss, log_loss
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.inspection import permutation_importance
    import sklearn
    import joblib

    sources = [s.strip() for s in args.source.split(',') if s.strip()]
    data = load_dataset(args.db, sources)
    if data is None or len(data['y']) < args.min_rows:
        n = 0 if data is None else len(data['y'])
        sys.exit(f"❌ Mới có {n} mẫu có nhãn (cần >= {args.min_rows}) — chạy backfill_dataset.py trước.")

    X, y, rule, ts = data['X'], data['y'], data['rule'], data['ts']
    print(f"📦 Dataset: {len(y)} mẫu ({', '.join(sources)}) | win rate {100 * y.mean():.1f}% "
          f"| {ts.min().date()} → {ts.max().date()}")

    folds = walk_forward_folds(ts)
    if not folds:
        sys.exit("❌ Không đủ dữ liệu để chia fold walk-forward.")
    print(f"🧪 Purged walk-forward: {len(folds)} fold, embargo {EMBARGO_DAYS} ngày\n")

    factories = make_models()
    results = {name: {'auc': [], 'brier': [], 'logloss': [], 'p10': [], 'p20': []} for name in factories}
    rule_aucs, pooled = [], {name: ([], []) for name in factories}  # (probs, y_true) gộp các fold

    for fi, (tr, va) in enumerate(folds, 1):
        base = float(y[va].mean())
        try:
            rule_auc = roc_auc_score(y[va], rule[va])
        except ValueError:
            rule_auc = float('nan')
        rule_aucs.append(rule_auc)
        line = f"Fold {fi}: train {len(tr)} | val {len(va)} (win {100 * base:.0f}%) | rule AUC {rule_auc:.3f}"
        for name, make in factories.items():
            model = make()
            model.fit(X.iloc[tr], y[tr])
            prob = model.predict_proba(X.iloc[va])[:, 1]
            r = results[name]
            r['auc'].append(roc_auc_score(y[va], prob))
            r['brier'].append(brier_score_loss(y[va], prob))
            r['logloss'].append(log_loss(y[va], prob, labels=[0, 1]))
            r['p10'].append(precision_at(y[va], prob, 0.10))
            r['p20'].append(precision_at(y[va], prob, 0.20))
            pooled[name][0].extend(prob)
            pooled[name][1].extend(y[va])
            line += f" | {name} AUC {r['auc'][-1]:.3f}"
        print(line)

    print()
    means = {}
    for name, r in results.items():
        means[name] = {k: float(np.nanmean(v)) for k, v in r.items()}
        m = means[name]
        print(f"📊 {name}: AUC {m['auc']:.3f} | Brier {m['brier']:.3f} | logloss {m['logloss']:.3f}"
              f" | P@10% {m['p10']:.2f} | P@20% {m['p20']:.2f}")
    rule_auc_mean = float(np.nanmean(rule_aucs))
    print(f"📊 baseline rule_score: AUC {rule_auc_mean:.3f} (model phải hơn >= +{SHIP_MIN_EDGE_VS_RULE})")

    winner = max(means, key=lambda n: means[n]['auc'])
    if abs(means['logistic']['auc'] - means['hist_gb']['auc']) < 1e-9:
        winner = 'logistic'  # hòa → chọn model đơn giản hơn
    win_auc = means[winner]['auc']
    print(f"\n🏆 Model thắng: {winner} (AUC {win_auc:.3f})")

    # Bảng calibration decile trên dự đoán pooled của model thắng
    probs = np.array(pooled[winner][0])
    truth = np.array(pooled[winner][1])
    buckets = np.clip((probs * 10).astype(int), 0, 9)
    print("\n🎯 Calibration (gộp các fold validation):")
    print("   decile | n    | prob TB | win thực tế")
    mono_x, mono_y = [], []
    for b in range(10):
        mask = buckets == b
        if mask.sum() == 0:
            continue
        actual = float(truth[mask].mean())
        print(f"   {b * 10:3d}-{b * 10 + 9}% | {mask.sum():4d} | {float(probs[mask].mean()):.2f}    | {actual:.2f}")
        if mask.sum() >= 30:
            mono_x.append(b)
            mono_y.append(actual)
    calib_mono = len(mono_x) >= 3 and float(np.corrcoef(mono_x, mono_y)[0, 1]) > 0
    print(f"   → Đơn điệu thô: {'✅ CÓ' if calib_mono else '❌ KHÔNG'}")

    # Permutation importance trên fold cuối
    tr, va = folds[-1]
    last_model = factories[winner]()
    last_model.fit(X.iloc[tr], y[tr])
    X_va_imp = X.iloc[va].fillna(X.iloc[tr].median())  # permutation_importance không ăn NaN với mọi model
    imp = permutation_importance(last_model, X_va_imp, y[va], scoring='roc_auc', n_repeats=5, random_state=42)
    order = np.argsort(-imp.importances_mean)[:10]
    print("\n🔍 Top 10 feature quan trọng (permutation, fold cuối):")
    for i in order:
        print(f"   {X.columns[i]:28s} {imp.importances_mean[i]:+.4f}")

    # Ngưỡng ship
    ship_ok = (win_auc >= SHIP_MIN_AUC) and (win_auc >= rule_auc_mean + SHIP_MIN_EDGE_VS_RULE) and calib_mono
    print(f"\n{'=' * 60}")
    print(f"Ngưỡng ship: AUC >= {SHIP_MIN_AUC} {'✅' if win_auc >= SHIP_MIN_AUC else '❌'}"
          f" | hơn rule +{SHIP_MIN_EDGE_VS_RULE} {'✅' if win_auc >= rule_auc_mean + SHIP_MIN_EDGE_VS_RULE else '❌'}"
          f" | calibration {'✅' if calib_mono else '❌'}")
    if not ship_ok and not args.force:
        sys.exit("❌ RỚT ngưỡng ship — KHÔNG ghi model. (Dùng --force nếu chỉ muốn thử nghiệm pipeline.)")
    if not ship_ok:
        print("⚠️ RỚT ngưỡng ship nhưng có --force — ghi model để THỬ NGHIỆM, đừng tin con số nó in ra.")

    # Train model cuối trên TOÀN BỘ dữ liệu + calibrate xác suất (hiển thị "% thắng" nên bắt buộc)
    method = 'isotonic' if len(y) > 8000 else 'sigmoid'
    final = CalibratedClassifierCV(factories[winner](), method=method, cv=5)
    final.fit(X, y)

    version = f"v1-{datetime.datetime.now().strftime('%Y%m%d')}"
    payload = {
        'pipeline': final,
        'feature_names': list(ml_features.PRICE_FEATURE_NAMES),
        'version': version,
        'trained_at': datetime.datetime.now().isoformat(timespec='seconds'),
        'n_train': int(len(y)),
        'label_spec': ml_features.LABEL_SPEC,
        'sklearn_version': sklearn.__version__,
        'metrics': {
            'winner': winner, 'walk_forward_auc': round(win_auc, 4),
            'rule_baseline_auc': round(rule_auc_mean, 4),
            'brier': round(means[winner]['brier'], 4),
            'precision_at_10pct': round(means[winner]['p10'], 4),
            'precision_at_20pct': round(means[winner]['p20'], 4),
            'calibration': method, 'ship_ok': bool(ship_ok),
        },
    }
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    joblib.dump(payload, args.out)
    print(f"\n✅ Đã ghi model {version} ({winner}, calibrate {method}, {len(y)} mẫu) → {args.out}")
    print("   Restart bot để dòng 🤖 ML xuất hiện trong tin kèo (shadow mode).")


if __name__ == '__main__':
    main()
