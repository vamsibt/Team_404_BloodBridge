# app/routers/patient.py
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
import uuid
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from typing import Optional
from app import models
from app.database import get_db
from app.deps import get_current_user
from app.services.upload import upload_file_to_s3
from app.services.plan import schedule_first_request, sync_plan_to_patient
import datetime

router = APIRouter()


class PatientProfileCreate(BaseModel):
    age: int = Field(..., ge=1, le=120)
    gender: Optional[str] = None
    city: str
    state: str
    pincode: Optional[str] = None
    hospital_id: Optional[str] = None
    hplc_unique_id: str
    thalassemia_type: Optional[str] = None
    guardian_name: Optional[str] = None
    guardian_phone: Optional[str] = None
    notes: Optional[str] = None


class PatientProfileUpdate(BaseModel):
    age: Optional[int] = Field(None, ge=1, le=120)
    gender: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    pincode: Optional[str] = None
    hospital_id: Optional[str] = None
    hplc_unique_id: Optional[str] = None
    thalassemia_type: Optional[str] = None
    guardian_name: Optional[str] = None
    guardian_phone: Optional[str] = None
    notes: Optional[str] = None


class TransfusionPlanCreate(BaseModel):
    blood_type: str
    packets_per_transfusion: int = Field(..., ge=1, le=10)
    interval_days: int = Field(..., ge=7, le=90, description='Days between transfusions')


class TransfusionPlanUpdate(BaseModel):
    blood_type: Optional[str] = None
    packets_per_transfusion: Optional[int] = Field(None, ge=1, le=10)
    interval_days: Optional[int] = Field(None, ge=7, le=90)
    is_active: Optional[bool] = None


def _patient_to_dict(patient: models.PatientProfile) -> dict:
    return {
        'id': patient.id,
        'user_id': patient.user_id,
        'blood_type': patient.blood_type,
        'age': patient.age,
        'gender': patient.gender,
        'city': patient.city,
        'state': patient.state,
        'pincode': patient.pincode,
        'hospital_id': patient.hospital_id,
        'hplc_doc_url': patient.hplc_doc_url,
        'hplc_unique_id': patient.hplc_unique_id,
        'is_admin_verified': patient.is_admin_verified,
        'thalassemia_type': patient.thalassemia_type,
        'transfusion_interval_days': patient.transfusion_interval_days,
        'next_transfusion_date': patient.next_transfusion_date,
        'guardian_name': patient.guardian_name,
        'guardian_phone': patient.guardian_phone,
        'notes': patient.notes,
        'current_bridge_id': patient.current_bridge_id,
        'created_at': patient.created_at,
    }


def _ensure_valid_hospital_id(hospital_id: Optional[str], db: Session) -> Optional[str]:
    if not hospital_id:
        return None
    try:
        hospital_uuid = str(uuid.UUID(hospital_id))
    except Exception:
        raise HTTPException(400, 'Selected hospital does not exist')
    hospital = db.query(models.Hospital).filter(models.Hospital.id == hospital_uuid).first()
    if not hospital:
        raise HTTPException(400, 'Selected hospital does not exist')
    return hospital_uuid


def _plan_to_dict(plan: models.TransfusionPlan) -> dict:
    return {
        'id': plan.id,
        'patient_id': plan.patient_id,
        'blood_type': plan.blood_type,
        'packets_per_transfusion': plan.packets_per_transfusion,
        'interval_days': plan.interval_days,
        'is_active': plan.is_active,
        'next_due_date': plan.next_due_date,
        'created_at': plan.created_at,
        'updated_at': plan.updated_at,
    }


@router.post('/register')
def register_patient(
    profile: PatientProfileCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if db.query(models.PatientProfile).filter(models.PatientProfile.user_id == current_user.id).first():
        raise HTTPException(400, 'Patient profile already exists')
    hosp_id = _ensure_valid_hospital_id(profile.hospital_id, db)
    patient = models.PatientProfile(
        user_id=current_user.id,
        blood_type='',
        age=profile.age,
        gender=profile.gender,
        city=profile.city,
        state=profile.state,
        pincode=profile.pincode,
        hospital_id=hosp_id,
        hplc_unique_id=profile.hplc_unique_id,
        thalassemia_type=profile.thalassemia_type,
        guardian_name=profile.guardian_name,
        guardian_phone=profile.guardian_phone,
        notes=profile.notes,
    )
    db.add(patient)
    db.commit()
    db.refresh(patient)
    return {
        'patient_id': patient.id,
        'message': 'Profile created. Please create your transfusion plan next.',
    }


@router.put('/me')
def update_patient_profile(
    body: PatientProfileUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    patient = db.query(models.PatientProfile).filter(models.PatientProfile.user_id == current_user.id).first()
    if not patient:
        raise HTTPException(404, 'Patient profile not found')
    updates = body.model_dump(exclude_unset=True)
    # sanitize hospital_id if present
    if 'hospital_id' in updates:
        val = updates.get('hospital_id')
        if val:
            try:
                updates['hospital_id'] = str(uuid.UUID(val))
            except Exception:
                updates['hospital_id'] = None
        else:
            updates['hospital_id'] = None

    for field, value in updates.items():
        setattr(patient, field, value)
    db.commit()
    db.refresh(patient)
    return {'profile': _patient_to_dict(patient), 'message': 'Profile updated'}


@router.post('/plan')
def create_plan(
    body: TransfusionPlanCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    patient = db.query(models.PatientProfile).filter(models.PatientProfile.user_id == current_user.id).first()
    if not patient:
        raise HTTPException(404, 'Patient profile not found. Register your profile first.')
    if db.query(models.TransfusionPlan).filter(models.TransfusionPlan.patient_id == patient.id).first():
        raise HTTPException(400, 'Transfusion plan already exists. Use PUT /plan to update.')

    plan = models.TransfusionPlan(
        patient_id=patient.id,
        blood_type=body.blood_type,
        packets_per_transfusion=body.packets_per_transfusion,
        interval_days=body.interval_days,
    )
    db.add(plan)
    db.flush()
    schedule_first_request(db, patient, plan)
    db.commit()
    db.refresh(plan)
    return {
        'plan_id': plan.id,
        'blood_type': plan.blood_type,
        'packets_per_transfusion': plan.packets_per_transfusion,
        'interval_days': plan.interval_days,
        'next_due_date': plan.next_due_date,
        'message': 'Transfusion plan created. First request submitted to admin.',
    }


@router.get('/plan')
def get_plan(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    patient = db.query(models.PatientProfile).filter(models.PatientProfile.user_id == current_user.id).first()
    if not patient:
        raise HTTPException(404, 'Patient profile not found')
    plan = db.query(models.TransfusionPlan).filter(models.TransfusionPlan.patient_id == patient.id).first()
    if not plan:
        raise HTTPException(404, 'No transfusion plan found. Create one with POST /plan.')
    return _plan_to_dict(plan)


@router.put('/plan')
def update_plan(
    body: TransfusionPlanUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    patient = db.query(models.PatientProfile).filter(models.PatientProfile.user_id == current_user.id).first()
    if not patient:
        raise HTTPException(404, 'Patient profile not found')
    plan = db.query(models.TransfusionPlan).filter(models.TransfusionPlan.patient_id == patient.id).first()
    if not plan:
        raise HTTPException(404, 'No transfusion plan found')

    updates = body.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(plan, field, value)

    if body.interval_days is not None and plan.next_due_date:
        plan.next_due_date = datetime.datetime.utcnow() + datetime.timedelta(days=plan.interval_days)

    sync_plan_to_patient(patient, plan)
    plan.updated_at = datetime.datetime.utcnow()
    db.commit()
    db.refresh(plan)
    return {
        'plan_id': plan.id,
        'blood_type': plan.blood_type,
        'packets_per_transfusion': plan.packets_per_transfusion,
        'interval_days': plan.interval_days,
        'is_active': plan.is_active,
        'next_due_date': plan.next_due_date,
        'message': 'Transfusion plan updated',
    }


@router.post('/upload-hplc')
async def upload_patient_hplc(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    url = await upload_file_to_s3(file, folder='hplc/patients')
    patient = db.query(models.PatientProfile).filter(models.PatientProfile.user_id == current_user.id).first()
    if not patient:
        raise HTTPException(404, 'Patient profile not found')
    patient.hplc_doc_url = url
    db.commit()
    return {'hplc_url': url}


@router.get('/me')
def get_patient_profile(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    patient = db.query(models.PatientProfile).filter(models.PatientProfile.user_id == current_user.id).first()
    if not patient:
        raise HTTPException(404, 'Profile not found')
    plan = db.query(models.TransfusionPlan).filter(models.TransfusionPlan.patient_id == patient.id).first()
    user = db.query(models.User).filter(models.User.id == current_user.id).first()
    profile_dict = _patient_to_dict(patient)
    profile_dict['latitude'] = user.latitude if user else None
    profile_dict['longitude'] = user.longitude if user else None
    return {
        'profile': profile_dict,
        'plan': _plan_to_dict(plan) if plan else None,
    }


@router.get('/my-requests')
def get_my_requests(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    patient = db.query(models.PatientProfile).filter(models.PatientProfile.user_id == current_user.id).first()
    if not patient:
        raise HTTPException(404, 'Patient profile not found')
    return db.query(models.TransfusionRequest).filter(
        models.TransfusionRequest.patient_id == patient.id,
    ).order_by(models.TransfusionRequest.created_at.desc()).all()
