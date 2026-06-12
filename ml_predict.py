# ==========================================
# ML PREDICT — load model + dự đoán xác suất kèo (SHADOW MODE)
# ==========================================
# Nguyên tắc sống còn: file này KHÔNG ĐƯỢC làm bot chết.
# Thiếu models/signal_model.pkl, thiếu sklearn/joblib, model lỗi version...
# → predict_signal_prob trả (None, None) và bot chạy y hệt như chưa có ML.

import os

import ml_features

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(BASE_DIR, 'models', 'signal_model.pkl')

_cache = {'tried': False, 'payload': None}


def load_model(force=False):
    """Load + cache payload model. Trả None nếu không load được (mọi lý do)."""
    if _cache['tried'] and not force:
        return _cache['payload']
    _cache['tried'] = True
    _cache['payload'] = None
    if not os.path.exists(MODEL_PATH):
        return None
    try:
        import joblib  # guarded: chưa cài sklearn/joblib thì bot vẫn sống
        payload = joblib.load(MODEL_PATH)
        # Payload phải đủ đồ nghề mới được dùng
        if not all(k in payload for k in ('pipeline', 'feature_names', 'version')):
            print(f"⚠️ ML: {MODEL_PATH} thiếu trường bắt buộc — bỏ qua model.")
            return None
        _cache['payload'] = payload
    except Exception as e:
        print(f"⚠️ ML: không load được model ({e}) — bot chạy tiếp KHÔNG có ML.")
        _cache['payload'] = None
    return _cache['payload']


def get_model_info():
    """Metadata model cho lệnh /ml và log khởi động (None nếu chưa có model)"""
    payload = load_model()
    if not payload:
        return None
    return {
        'version': payload.get('version'),
        'trained_at': payload.get('trained_at'),
        'n_train': payload.get('n_train'),
        'metrics': payload.get('metrics', {}),
        'label_spec': payload.get('label_spec'),
        'sklearn_version': payload.get('sklearn_version'),
    }


def predict_signal_prob(features):
    """features: dict (có thể lẫn key thừa — chỉ lấy đúng feature_names của model).
    Trả (prob: float 0-1, version: str) hoặc (None, None)."""
    payload = load_model()
    if not payload:
        return None, None
    try:
        import pandas as pd
        names = payload['feature_names']
        row = {name: features.get(name) for name in names}
        X = pd.DataFrame([row], columns=names).astype(float)  # None → NaN
        prob = float(payload['pipeline'].predict_proba(X)[0, 1])
        return prob, payload.get('version', '?')
    except Exception as e:
        print(f"⚠️ ML: predict lỗi ({e}) — kèo này không có điểm ML.")
        return None, None
