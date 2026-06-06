# app/routers/donor.py
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from app import models
from app.database import get_db
from app.deps import get_current_user
from app.services.upload import upload_file_to_s3
import datetime

router = APIRouter()

class DonorProfileCreate(BaseModel):
    blood_type: str
    age: int
    weight: float
    city: str
    state: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    hplc_unique_id: str
    donor_type: str = 'bridge'   # bridge | emergency

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

@router.post('/register')
def register_donor(
    profile: DonorProfileCreate,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    if db.query(models.DonorProfile).filter(models.DonorProfile.user_id == current_user.id).first():
        raise HTTPException(400, 'Donor profile already exists')
    donor = models.DonorProfile(
        user_id=current_user.id,
        blood_type=profile.blood_type,
        age=profile.age,
        weight=profile.weight,
        city=profile.city,
        state=profile.state,
        latitude=profile.latitude,
        longitude=profile.longitude,
        hplc_unique_id=profile.hplc_unique_id,
        donor_type=models.BridgeType[profile.donor_type]
    )
    db.add(donor); db.commit(); db.refresh(donor)
    return {'donor_id': donor.id, 'message': 'Profile created. Pending admin verification.'}

@router.post('/upload-hplc')
async def upload_donor_hplc(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
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
    current_user = Depends(get_current_user)
):
    donor = db.query(models.DonorProfile).filter(models.DonorProfile.user_id == current_user.id).first()
    if not donor:
        raise HTTPException(404, 'Donor profile not found')
    fail_reasons = []
    if not screening.weight_adequate: fail_reasons.append('weight_adequate')
    if not screening.age_in_range: fail_reasons.append('age_in_range')
    if screening.has_low_hemoglobin: fail_reasons.append('has_low_hemoglobin')
    if screening.donated_recently: fail_reasons.append('donated_recently')
    if screening.recent_illness_or_meds: fail_reasons.append('recent_illness_or_meds')
    if screening.recent_tattoo_piercing: fail_reasons.append('recent_tattoo_piercing')
    if screening.recent_surgery_dental: fail_reasons.append('recent_surgery_dental')
    if screening.pregnant_or_breastfeeding: fail_reasons.append('pregnant_or_breastfeeding')
    if screening.chronic_disease: fail_reasons.append('chronic_disease')
    if screening.blood_disorder: fail_reasons.append('blood_disorder')
    if screening.infectious_disease: fail_reasons.append('infectious_disease')
    passed = len(fail_reasons) == 0
    log = models.DonorEligibilityLog(
        donor_id=donor.id,
        screening_passed=passed,
        responses_json={'questions': screening.model_dump(), 'fail_reasons': fail_reasons}
    )
    db.add(log); db.commit()
    return {'passed': passed, 'fail_reasons': fail_reasons}

@router.get('/me')
def get_my_profile(db: Session = Depends(get_db), current_user = Depends(get_current_user)):
    donor = db.query(models.DonorProfile).filter(models.DonorProfile.user_id == current_user.id).first()
    if not donor:
        raise HTTPException(404, 'Donor profile not found')
    return donor

@router.get('/my-schedule')
def get_donation_schedule(db: Session = Depends(get_db), current_user = Depends(get_current_user)):
    donor = db.query(models.DonorProfile).filter(models.DonorProfile.user_id == current_user.id).first()
    if not donor:
        raise HTTPException(404, 'Donor profile not found')
    upcoming = db.query(models.TransfusionRequest).filter(
        models.TransfusionRequest.assigned_donor_id == donor.id,
        models.TransfusionRequest.status.in_([
            models.RequestStatus.approved,
            models.RequestStatus.assigned,
            models.RequestStatus.scheduled,
        ])
    ).all()
    return upcoming
