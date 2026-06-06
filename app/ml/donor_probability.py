import os
import joblib
import numpy as np

BASE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'ml', 'donor_probability')
MODEL_PATH = os.path.join(BASE_DIR, 'donor_model.pkl')
SCALER_PATH = os.path.join(BASE_DIR, 'scaler.pkl')

_model = None
_scaler = None


def _load():
    global _model, _scaler
    if _model is None or _scaler is None:
        _model = joblib.load(MODEL_PATH)
        _scaler = joblib.load(SCALER_PATH)
    return _model, _scaler


def predict_donation_probability(donors: list[dict]) -> list[dict]:
    if not donors:
        return []
    model, scaler = _load()
    features = []
    donor_ids = []
    for donor in donors:
        features.append([
            float(donor.get('recency', 0)),
            float(donor.get('frequency', 0)),
            float(donor.get('monetary', 0)),
            float(donor.get('time', 0)),
        ])
        donor_ids.append(donor['donor_id'])
    scaled = scaler.transform(np.array(features))
    probabilities = model.predict_proba(scaled)[:, 1]
    results = [
        {'donor_id': donor_id, 'probability': round(float(prob), 4)}
        for donor_id, prob in zip(donor_ids, probabilities)
    ]
    results.sort(key=lambda x: x['probability'], reverse=True)
    return results
