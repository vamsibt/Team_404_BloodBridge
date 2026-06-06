import os
import joblib
import pandas as pd

BASE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'ml', 'models')

BLOOD_GROUP_MAP = {
    'O+': 0, 'O-': 1, 'A+': 2, 'A-': 3,
    'B+': 4, 'B-': 5, 'AB+': 6, 'AB-': 7,
}

_cache = {}


def load_model_payload(name: str) -> dict:
    if name not in _cache:
        path = os.path.join(BASE_DIR, name)
        if not os.path.exists(path):
            raise FileNotFoundError(f'Model not found: {path}')
        _cache[name] = joblib.load(path)
    return _cache[name]


def predict_with_payload(payload: dict, features: dict) -> dict:
    model = payload['model']
    feature_names = payload['features']
    scaler = payload.get('scaler')
    use_scaled = payload.get('use_scaled', False)

    row = pd.DataFrame([{f: features.get(f, 0) for f in feature_names}])
    input_data = scaler.transform(row) if use_scaled and scaler is not None else row
    prediction = int(model.predict(input_data)[0])
    confidence = None
    if hasattr(model, 'predict_proba'):
        proba = model.predict_proba(input_data)[0]
        confidence = round(float(max(proba)), 4)
    return {'prediction': prediction, 'confidence': confidence}
