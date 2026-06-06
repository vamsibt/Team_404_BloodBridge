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
    patient_city: str
    patient_state: str
    urgency: str = 'normal'
    top_k: int = 10


class EligibilityPredictRequest(BaseModel):
    age: int
    weight: float
    last_donated_days_ago: Optional[int] = None
    has_chronic_disease: bool = False
    has_recent_illness: bool = False


class PriorityScoreInput(BaseModel):
    hemoglobin: Optional[float] = None
    age: Optional[int] = None
    days_since_last_transfusion: Optional[int] = None
    urgency_tier: Optional[str] = None
    medical_notes: Optional[str] = None


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


@router.post('/find-donors')
def find_best_donors(
    req: DonorFindRequest,
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    donors = db.query(models.DonorProfile).filter(
        models.DonorProfile.blood_type == req.blood_type,
        models.DonorProfile.is_admin_verified == True,
        models.DonorProfile.availability == True,
    ).all()

    scored = []
    try:
        payload = load_model_payload('donor_availability_model.pkl')
        for d in donors:
            result = predict_with_payload(payload, donor_availability_features(d))
            label = AVAILABILITY_LABELS.get(result['prediction'], str(result['prediction']))
            scored.append({
                'id': d.id,
                'city': d.city,
                'total_donations': d.total_donations,
                'availability_prediction': label,
                'confidence': result['confidence'],
            })
        scored.sort(key=lambda x: x.get('confidence') or 0, reverse=True)
    except FileNotFoundError:
        scored = [{'id': d.id, 'city': d.city, 'total_donations': d.total_donations} for d in donors]

    return {'donors': scored[:req.top_k]}


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
