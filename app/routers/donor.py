# app/routers/donor.py
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
import uuid
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from typing import Optional, Literal
from app import models
from app.database import get_db
from app.deps import get_current_user
from app.services.upload import upload_file_to_s3
from app.services.notification import send_notification
from app.services.bridge import get_current_turn_donor
import datetime

router = APIRouter()


class DonorProfileCreate(BaseModel):
    blood_type: str = Field(
        ..., strip_whitespace=True, min_length=2, max_length=3,
        pattern=r'^(A|B|AB|O)[+-]$',
    )
    age: int = Field(..., ge=18, le=65)
    weight: float = Field(..., ge=45)
    gender: Optional[Literal['Male', 'Female', 'Other']] = None
    city: str
    state: str
    pincode: Optional[str] = None
    hospital_id: Optional[uuid.UUID] = None
    hplc_unique_id: str
    donor_type: Literal['bridge', 'emergency'] = 'bridge'
    notes: Optional[str] = None

    model_config = {
        'extra': 'forbid',
    }


class DonorProfileUpdate(BaseModel):
    blood_type: Optional[str] = Field(
        None, strip_whitespace=True, min_length=2, max_length=3,
        pattern=r'^(A|B|AB|O)[+-]$',
    )
    age: Optional[int] = Field(None, ge=18, le=65)
    weight: Optional[float] = Field(None, ge=45)
    gender: Optional[Literal['Male', 'Female', 'Other']] = None
    city: Optional[str] = None
    state: Optional[str] = None
    pincode: Optional[str] = None
    hospital_id: Optional[uuid.UUID] = None
    hplc_unique_id: Optional[str] = None
    donor_type: Optional[Literal['bridge', 'emergency']] = None
    availability: Optional[bool] = None
    notes: Optional[str] = None

    model_config = {
        'extra': 'forbid',
    }


class EligibilityScreening(BaseModel):
    weight_adequate: bool
    age_in_range: bool
    has_low_hemoglobin: bool
    donated_recently: bool
    recent_illness_or_meds: bool
    recent_tattoo_piercing: bool
    recent_surgery_dental: bool
    pregnant_or_breastfeeding: bool
    chronic_disease: bool
    blood_disorder: bool
    infectious_disease: bool


def _donor_to_dict(donor: models.DonorProfile) -> dict:
    return {
        'id': donor.id,
        'user_id': donor.user_id,
        'blood_type': donor.blood_type,
        'age': donor.age,
        'weight': donor.weight,
        'gender': donor.gender,
        'city': donor.city,
        'state': donor.state,
        'pincode': donor.pincode,
        'latitude': donor.latitude,
        'longitude': donor.longitude,
        'hospital_id': donor.hospital_id,
        'hplc_doc_url': donor.hplc_doc_url,
        'hplc_unique_id': donor.hplc_unique_id,
        'is_admin_verified': donor.is_admin_verified,
        'donor_type': donor.donor_type.value if donor.donor_type else 'bridge',
        'availability': donor.availability,
        'total_donations': donor.total_donations,
        'last_donated_at': donor.last_donated_at,
        'notes': donor.notes,
        'created_at': donor.created_at,
    }


def _resolve_coords(profile_lat, profile_lon, user):
    if profile_lat is not None and profile_lon is not None:
        return profile_lat, profile_lon
    if user and user.latitude is not None and user.longitude is not None:
        return user.latitude, user.longitude
    return None, None


def _ensure_valid_hospital_id(hospital_id: Optional[uuid.UUID], db: Session) -> Optional[str]:
    if hospital_id is None:
        return None
    hospital = db.query(models.Hospital).filter(models.Hospital.id == hospital_id).first()
    if not hospital:
        raise HTTPException(400, 'Selected hospital does not exist')
    return str(hospital_id)


@router.post('/register')
def register_donor(
    profile: DonorProfileCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if db.query(models.DonorProfile).filter(models.DonorProfile.user_id == current_user.id).first():
        raise HTTPException(400, 'Donor profile already exists')
    lat, lon = _resolve_coords(None, None, current_user)
    hosp_id = _ensure_valid_hospital_id(profile.hospital_id, db)

    donor = models.DonorProfile(
        user_id=current_user.id,
        blood_type=profile.blood_type,
        age=profile.age,
        weight=profile.weight,
        gender=profile.gender,
        city=profile.city,
        state=profile.state,
        pincode=profile.pincode,
        latitude=lat,
        longitude=lon,
        hospital_id=hosp_id,
        hplc_unique_id=profile.hplc_unique_id,
        donor_type=models.BridgeType[profile.donor_type],
        notes=profile.notes,
    )
    db.add(donor)
    db.commit()
    db.refresh(donor)
    return {'donor_id': donor.id, 'message': 'Profile created. Pending admin verification.'}


@router.put('/me')
def update_donor_profile(
    body: DonorProfileUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    donor = db.query(models.DonorProfile).filter(models.DonorProfile.user_id == current_user.id).first()
    if not donor:
        raise HTTPException(404, 'Donor profile not found')
    updates = body.model_dump(exclude_unset=True)
    if 'donor_type' in updates:
        updates['donor_type'] = models.BridgeType[updates['donor_type']]
    if 'hospital_id' in updates:
        val = updates.get('hospital_id')
        updates['hospital_id'] = _ensure_valid_hospital_id(val, db)
    for field, value in updates.items():
        setattr(donor, field, value)

    if donor.latitude is None or donor.longitude is None:
        lat, lon = _resolve_coords(donor.latitude, donor.longitude, current_user)
        donor.latitude, donor.longitude = lat, lon

    db.commit()
    db.refresh(donor)
    return {'profile': _donor_to_dict(donor), 'message': 'Profile updated'}


@router.post('/upload-hplc')
async def upload_donor_hplc(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    url = await upload_file_to_s3(file, folder='hplc/donors')
    donor = db.query(models.DonorProfile).filter(models.DonorProfile.user_id == current_user.id).first()
    if not donor:
        raise HTTPException(404, 'Donor profile not found')
    donor.hplc_doc_url = url
    db.commit()
    return {'hplc_url': url}


@router.post('/eligibility-screening')
def submit_eligibility(
    screening: EligibilityScreening,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    donor = db.query(models.DonorProfile).filter(models.DonorProfile.user_id == current_user.id).first()
    if not donor:
        raise HTTPException(404, 'Donor profile not found')
    fail_reasons = []
    if not screening.weight_adequate:
        fail_reasons.append('weight_adequate')
    if not screening.age_in_range:
        fail_reasons.append('age_in_range')
    if screening.has_low_hemoglobin:
        fail_reasons.append('has_low_hemoglobin')
    if screening.donated_recently:
        fail_reasons.append('donated_recently')
    if screening.recent_illness_or_meds:
        fail_reasons.append('recent_illness_or_meds')
    if screening.recent_tattoo_piercing:
        fail_reasons.append('recent_tattoo_piercing')
    if screening.recent_surgery_dental:
        fail_reasons.append('recent_surgery_dental')
    if screening.pregnant_or_breastfeeding:
        fail_reasons.append('pregnant_or_breastfeeding')
    if screening.chronic_disease:
        fail_reasons.append('chronic_disease')
    if screening.blood_disorder:
        fail_reasons.append('blood_disorder')
    if screening.infectious_disease:
        fail_reasons.append('infectious_disease')
    passed = len(fail_reasons) == 0
    log = models.DonorEligibilityLog(
        donor_id=donor.id,
        screening_passed=passed,
        responses_json={'questions': screening.model_dump(), 'fail_reasons': fail_reasons},
    )
    db.add(log)
    db.commit()
    return {'passed': passed, 'fail_reasons': fail_reasons}


@router.get('/me')
def get_my_profile(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    donor = db.query(models.DonorProfile).filter(models.DonorProfile.user_id == current_user.id).first()
    if not donor:
        raise HTTPException(404, 'Donor profile not found')
    return _donor_to_dict(donor)


@router.get('/pending-requests')
def get_pending_requests(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    """Approved requests where this donor is the current-turn bridge donor."""
    donor = db.query(models.DonorProfile).filter(models.DonorProfile.user_id == current_user.id).first()
    if not donor:
        raise HTTPException(404, 'Donor profile not found')

    approved = db.query(models.TransfusionRequest).filter(
        models.TransfusionRequest.status == models.RequestStatus.approved,
    ).all()

    result = []
    for req in approved:
        patient = db.query(models.PatientProfile).filter(models.PatientProfile.id == req.patient_id).first()
        if not patient or not patient.current_bridge_id:
            continue
        turn_donor = get_current_turn_donor(db, patient.current_bridge_id)
        if turn_donor and turn_donor.id == donor.id:
            result.append(req)
    return result


@router.post('/accept-request/{request_id}')
def accept_request(
    request_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    donor = db.query(models.DonorProfile).filter(models.DonorProfile.user_id == current_user.id).first()
    if not donor:
        raise HTTPException(404, 'Donor profile not found')

    req = db.query(models.TransfusionRequest).filter(models.TransfusionRequest.id == request_id).first()
    if not req:
        raise HTTPException(404, 'Request not found')
    if req.status != models.RequestStatus.approved:
        raise HTTPException(400, 'Request is not awaiting donor acceptance')

    patient = db.query(models.PatientProfile).filter(models.PatientProfile.id == req.patient_id).first()
    if not patient or not patient.current_bridge_id:
        raise HTTPException(400, 'Patient has no bridge assigned')

    turn_donor = get_current_turn_donor(db, patient.current_bridge_id)
    if not turn_donor or turn_donor.id != donor.id:
        raise HTTPException(403, 'It is not your turn to accept this request')

    if not req.hospital_id:
        raise HTTPException(400, 'No hospital assigned to this request yet')

    hospital = db.query(models.Hospital).filter(models.Hospital.id == req.hospital_id).first()
    if not hospital or not hospital.coordinator_user_id:
        raise HTTPException(400, 'Hospital has no coordinator assigned')

    req.assigned_donor_id = donor.id
    req.status = models.RequestStatus.assigned

    existing = db.query(models.CoordinatorAssignment).filter(
        models.CoordinatorAssignment.request_id == req.id
    ).first()
    if not existing:
        assignment = models.CoordinatorAssignment(
            request_id=req.id,
            patient_id=patient.id,
            donor_id=donor.id,
            coordinator_id=hospital.coordinator_user_id,
            hospital_id=hospital.id,
            status='pending',
        )
        db.add(assignment)

    db.commit()

    send_notification(
        db, hospital.coordinator_user_id,
        'Donor Accepted Request',
        f'Donor {current_user.full_name} accepted transfusion request. Patient ID: {patient.id}, Donor ID: {donor.id}. Please schedule an appointment.',
    )
    send_notification(
        db, patient.user_id,
        'Donor Confirmed',
        f'A donor has accepted your transfusion request. The hospital coordinator will schedule your appointment shortly.',
    )

    return {
        'message': 'Request accepted. Coordinator notified to book appointment.',
        'request_id': req.id,
        'patient_id': patient.id,
        'donor_id': donor.id,
        'coordinator_id': hospital.coordinator_user_id,
    }


@router.get('/my-schedule')
def get_donation_schedule(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    donor = db.query(models.DonorProfile).filter(models.DonorProfile.user_id == current_user.id).first()
    if not donor:
        raise HTTPException(404, 'Donor profile not found')
    upcoming = db.query(models.TransfusionRequest).filter(
        models.TransfusionRequest.assigned_donor_id == donor.id,
        models.TransfusionRequest.status.in_([
            models.RequestStatus.approved,
            models.RequestStatus.assigned,
            models.RequestStatus.scheduled,
        ]),
    ).all()
    return upcoming
