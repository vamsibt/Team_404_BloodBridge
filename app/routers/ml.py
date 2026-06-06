# app/routers/ml.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from typing import Optional, List
from app.database import get_db
from app.deps import get_current_user, require_admin
from app import models
from app.ml.donor_probability import predict_donation_probability
from app.ml.model_loader import load_model_payload, predict_with_payload
from app.ml.features import (
    donor_availability_features,
    donor_churn_features,
    request_priority_features,
    CHURN_LABELS,
    PRIORITY_LABELS,
    AVAILABILITY_LABELS,
)
from app.ml.priority_engine import calculate_priority_score
from app.services.geo import donor_distance_km
from sqlalchemy.orm import joinedload

router = APIRouter()


class DonorFeatureInput(BaseModel):
    donor_id: str
    recency: float = Field(..., description='Months since last donation')
    frequency: int = Field(..., description='Total donations')
    monetary: float = Field(..., description='Total blood in c.c.')
    time: float = Field(..., description='Months since first donation')


class DonorProbabilityRequest(BaseModel):
    donors: List[DonorFeatureInput]


class DonorFindRequest(BaseModel):
    blood_type: str
    patient_city: str = ''
    patient_state: str = ''
    patient_latitude: Optional[float] = None
    patient_longitude: Optional[float] = None
    urgency: str = 'normal'
    top_k: int = 10
    max_distance_km: float = 200.0


class EligibilityPredictRequest(BaseModel):
    age: int
    weight: float
    last_donated_days_ago: Optional[int] = None
    has_chronic_disease: bool = False
    has_recent_illness: bool = False


class EligibilityBatchItem(EligibilityPredictRequest):
    donor_id: Optional[str] = None


class PriorityScoreInput(BaseModel):
    hemoglobin: Optional[float] = None
    age: Optional[int] = None
    days_since_last_transfusion: Optional[int] = None
    urgency_tier: Optional[str] = None
    medical_notes: Optional[str] = None


class DonorChurnBatchRequest(BaseModel):
    donor_ids: List[str]


class RequestPriorityBatchRequest(BaseModel):
    request_ids: List[str]


class EligibilityBatchRequest(BaseModel):
    donors: List[EligibilityBatchItem]


@router.post('/donor-probability')
def donor_probability(
    req: DonorProbabilityRequest,
    admin=Depends(require_admin),
):
    try:
        predictions = predict_donation_probability([d.model_dump() for d in req.donors])
        return {'status': 'success', 'predictions': predictions}
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc


def _resolve_patient_coords(db: Session, req: DonorFindRequest):
    if req.patient_latitude is not None and req.patient_longitude is not None:
        return req.patient_latitude, req.patient_longitude
    if req.patient_city:
        patient = db.query(models.PatientProfile).join(models.User).filter(
            models.PatientProfile.city.ilike(req.patient_city),
        ).first()
        if patient:
            user = db.query(models.User).filter(models.User.id == patient.user_id).first()
            if user and user.latitude is not None and user.longitude is not None:
                return user.latitude, user.longitude
    return None, None

COMPATIBLE_DONORS = {
    'O-': ['O-'],
    'O+': ['O-', 'O+'],
    'A-': ['O-', 'A-'],
    'A+': ['O-', 'O+', 'A-', 'A+'],
    'B-': ['O-', 'B-'],
    'B+': ['O-', 'O+', 'B-', 'B+'],
    'AB-': ['O-', 'A-', 'B-', 'AB-'],
    'AB+': ['O-', 'O+', 'A-', 'A+', 'B-', 'B+', 'AB-', 'AB+']
}

@router.post('/find-donors')
def find_best_donors(
    req: DonorFindRequest,
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    compatible_types = COMPATIBLE_DONORS.get(req.blood_type, [req.blood_type])
    donors = db.query(models.DonorProfile).options(
        joinedload(models.DonorProfile.user),
    ).filter(
        models.DonorProfile.blood_type.in_(compatible_types),
        models.DonorProfile.is_admin_verified == True,
        models.DonorProfile.availability == True,
        ~models.DonorProfile.bridge_assignments.any(
            models.BridgeAssignment.bridge.has(models.Bridge.is_active == True)
        )
    ).all()

    patient_lat, patient_lon = _resolve_patient_coords(db, req)
    use_geo = patient_lat is not None and patient_lon is not None

    scored = []
    try:
        avail_payload = load_model_payload('donor_availability_model.pkl')
        churn_payload = load_model_payload('donor_churn_model.pkl')
        for d in donors:
            distance_km = donor_distance_km(d, patient_lat, patient_lon, db) if use_geo else None
            if use_geo and distance_km is not None and distance_km > req.max_distance_km:
                continue
            avail_result = predict_with_payload(avail_payload, donor_availability_features(d))
            churn_result = predict_with_payload(churn_payload, donor_churn_features(d))
            avail_label = AVAILABILITY_LABELS.get(avail_result['prediction'], str(avail_result['prediction']))
            churn_label = CHURN_LABELS.get(churn_result['prediction'], str(churn_result['prediction']))
            confidence = avail_result.get('confidence') or 0
            geo_score = 1.0 / (1.0 + (distance_km or 0)) if use_geo else 0
            # Penalize HIGH_RISK churn donors slightly
            churn_penalty = 0.85 if churn_label == 'HIGH_RISK' else 1.0
            combined = ((confidence * 0.6) + (geo_score * 0.4)) * churn_penalty if use_geo else confidence * churn_penalty
            scored.append({
                'id': d.id,
                'city': d.city,
                'state': d.state,
                'blood_type': d.blood_type,
                'total_donations': d.total_donations,
                'availability_prediction': avail_label,
                'confidence': confidence,
                'churn_risk': churn_label,
                'churn_confidence': churn_result.get('confidence'),
                'distance_km': round(distance_km, 2) if distance_km is not None and distance_km < 9999 else None,
                'combined_score': round(combined, 4),
            })
        scored.sort(key=lambda x: x.get('combined_score') or x.get('confidence') or 0, reverse=True)
    except FileNotFoundError:
        for d in donors:
            distance_km = donor_distance_km(d, patient_lat, patient_lon, db) if use_geo else None
            if use_geo and distance_km is not None and distance_km > req.max_distance_km:
                continue
            geo_score = 1.0 / (1.0 + (distance_km or 0)) if use_geo else 0
            scored.append({
                'id': d.id,
                'city': d.city,
                'state': d.state,
                'blood_type': d.blood_type,
                'total_donations': d.total_donations,
                'distance_km': round(distance_km, 2) if distance_km is not None and distance_km < 9999 else None,
                'combined_score': round(geo_score, 4) if use_geo else None,
            })
        scored.sort(key=lambda x: x.get('combined_score') or 0, reverse=True)

    return {
        'donors': scored[:req.top_k],
        'search_coords': {'latitude': patient_lat, 'longitude': patient_lon} if use_geo else None,
    }


@router.get('/priority-requests')
def get_priority_requests(
    status: str = 'pending',
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    """Score all pending requests with the ML priority model and return them sorted."""
    query_status = getattr(models.RequestStatus, status, models.RequestStatus.pending)
    requests_list = db.query(models.TransfusionRequest).filter(
        models.TransfusionRequest.status == query_status
    ).order_by(models.TransfusionRequest.created_at.desc()).all()

    try:
        priority_payload = load_model_payload('request_priority_model.pkl')
    except FileNotFoundError:
        priority_payload = None

    PRIORITY_ORDER = {'CRITICAL': 0, 'HIGH': 1, 'MEDIUM': 2, 'LOW': 3}
    results = []
    for req_obj in requests_list:
        patient = db.query(models.PatientProfile).filter(
            models.PatientProfile.id == req_obj.patient_id
        ).first()
        if not patient:
            continue
        patient_user = db.query(models.User).filter(models.User.id == patient.user_id).first()
        plan = db.query(models.TransfusionPlan).filter(
            models.TransfusionPlan.patient_id == patient.id
        ).first()
        assigned = 0
        if patient.current_bridge_id:
            assigned = db.query(models.BridgeAssignment).filter(
                models.BridgeAssignment.bridge_id == patient.current_bridge_id
            ).count()

        priority_label = 'MEDIUM'
        priority_conf = None
        if priority_payload:
            try:
                p_result = predict_with_payload(
                    priority_payload, request_priority_features(patient, plan, assigned)
                )
                priority_label = PRIORITY_LABELS.get(p_result['prediction'], 'MEDIUM')
                priority_conf = p_result.get('confidence')
            except Exception:
                pass

        results.append({
            'request_id': req_obj.id,
            'patient_id': patient.id,
            'patient_name': patient_user.full_name if patient_user else None,
            'blood_type': patient.blood_type or (plan.blood_type if plan else None),
            'city': patient.city,
            'state': patient.state,
            'status': req_obj.status.value,
            'requested_date': req_obj.requested_date,
            'created_at': req_obj.created_at,
            'packets_required': req_obj.packets_required,
            'has_bridge': patient.current_bridge_id is not None,
            'bridge_donors': assigned,
            'priority': priority_label,
            'priority_confidence': priority_conf,
            'interval_days': plan.interval_days if plan else None,
            'next_due_date': plan.next_due_date if plan else None,
        })

    results.sort(key=lambda x: (PRIORITY_ORDER.get(x['priority'], 99), str(x['created_at'])))
    return results




@router.post('/predict-donor-availability/{donor_id}')
def predict_donor_availability(
    donor_id: str,
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    donor = db.query(models.DonorProfile).filter(models.DonorProfile.id == donor_id).first()
    if not donor:
        raise HTTPException(404, 'Donor not found')
    payload = load_model_payload('donor_availability_model.pkl')
    result = predict_with_payload(payload, donor_availability_features(donor))
    return {
        'donor_id': donor_id,
        'prediction': AVAILABILITY_LABELS.get(result['prediction'], result['prediction']),
        'confidence': result['confidence'],
    }


def _evaluate_eligibility(req: EligibilityPredictRequest) -> dict:
    eligible = True
    reasons = []
    if req.age < 18 or req.age > 65:
        eligible = False
        reasons.append('age_out_of_range')
    if req.weight < 45:
        eligible = False
        reasons.append('underweight')
    if req.last_donated_days_ago and req.last_donated_days_ago < 90:
        eligible = False
        reasons.append('donated_too_recently')
    if req.has_chronic_disease:
        eligible = False
        reasons.append('chronic_disease')
    if req.has_recent_illness:
        eligible = False
        reasons.append('recent_illness')
    return {'eligible': eligible, 'reasons': reasons}


@router.post('/predict-donor-churn/{donor_id}')
def predict_donor_churn(
    donor_id: str,
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    donor = db.query(models.DonorProfile).filter(models.DonorProfile.id == donor_id).first()
    if not donor:
        raise HTTPException(404, 'Donor not found')
    payload = load_model_payload('donor_churn_model.pkl')
    result = predict_with_payload(payload, donor_churn_features(donor))
    return {
        'donor_id': donor_id,
        'prediction': CHURN_LABELS.get(result['prediction'], result['prediction']),
        'confidence': result['confidence'],
    }


@router.post('/predict-donor-churn')
def predict_donor_churn_batch(
    req: DonorChurnBatchRequest,
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    donors = db.query(models.DonorProfile).filter(models.DonorProfile.id.in_(req.donor_ids)).all()
    donor_map = {d.id: d for d in donors}
    payload = load_model_payload('donor_churn_model.pkl')
    predictions = []
    for donor_id in req.donor_ids:
        donor = donor_map.get(donor_id)
        if not donor:
            predictions.append({'donor_id': donor_id, 'error': 'Donor not found'})
            continue
        result = predict_with_payload(payload, donor_churn_features(donor))
        predictions.append({
            'donor_id': donor_id,
            'prediction': CHURN_LABELS.get(result['prediction'], result['prediction']),
            'confidence': result['confidence'],
        })
    return {'predictions': predictions}


@router.post('/predict-request-priority/{request_id}')
def predict_request_priority(
    request_id: str,
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    req = db.query(models.TransfusionRequest).filter(models.TransfusionRequest.id == request_id).first()
    if not req:
        raise HTTPException(404, 'Request not found')
    patient = db.query(models.PatientProfile).filter(models.PatientProfile.id == req.patient_id).first()
    plan = db.query(models.TransfusionPlan).filter(models.TransfusionPlan.patient_id == patient.id).first()
    assigned = 0
    if patient.current_bridge_id:
        assigned = db.query(models.BridgeAssignment).filter(
            models.BridgeAssignment.bridge_id == patient.current_bridge_id
        ).count()
    payload = load_model_payload('request_priority_model.pkl')
    result = predict_with_payload(payload, request_priority_features(patient, plan, assigned))
    return {
        'request_id': request_id,
        'prediction': PRIORITY_LABELS.get(result['prediction'], result['prediction']),
        'confidence': result['confidence'],
    }


@router.post('/predict-request-priority')
def predict_request_priority_batch(
    req: RequestPriorityBatchRequest,
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    requests = db.query(models.TransfusionRequest).filter(models.TransfusionRequest.id.in_(req.request_ids)).all()
    request_map = {r.id: r for r in requests}
    payload = load_model_payload('request_priority_model.pkl')
    predictions = []
    for request_id in req.request_ids:
        req_obj = request_map.get(request_id)
        if not req_obj:
            predictions.append({'request_id': request_id, 'error': 'Request not found'})
            continue
        patient = db.query(models.PatientProfile).filter(models.PatientProfile.id == req_obj.patient_id).first()
        if not patient:
            predictions.append({'request_id': request_id, 'error': 'Patient not found'})
            continue
        plan = db.query(models.TransfusionPlan).filter(models.TransfusionPlan.patient_id == patient.id).first()
        assigned = 0
        if patient.current_bridge_id:
            assigned = db.query(models.BridgeAssignment).filter(
                models.BridgeAssignment.bridge_id == patient.current_bridge_id
            ).count()
        result = predict_with_payload(payload, request_priority_features(patient, plan, assigned))
        predictions.append({
            'request_id': request_id,
            'prediction': PRIORITY_LABELS.get(result['prediction'], result['prediction']),
            'confidence': result['confidence'],
        })
    return {'predictions': predictions}


@router.post('/priority-score')
def priority_score(
    req: PriorityScoreInput,
    current_user=Depends(get_current_user),
):
    return {'status': 'success', **calculate_priority_score(**req.model_dump())}


@router.post('/predict-eligibility')
def predict_eligibility(
    req: EligibilityPredictRequest,
    current_user=Depends(get_current_user),
):
    return _evaluate_eligibility(req)


@router.post('/predict-eligibility/batch')
def predict_eligibility_batch(
    req: EligibilityBatchRequest,
    admin=Depends(require_admin),
):
    return {
        'results': [
            {
                **({'donor_id': d.donor_id} if d.donor_id else {'donor_index': i}),
                **_evaluate_eligibility(d),
            }
            for i, d in enumerate(req.donors)
        ]
    }
