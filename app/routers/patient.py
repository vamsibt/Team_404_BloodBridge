# app/routers/patient.py
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
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
    age: int
    city: str
    state: str
    hplc_unique_id: str


class TransfusionPlanCreate(BaseModel):
    blood_type: str
    packets_per_transfusion: int = Field(..., ge=1, le=10)
    interval_days: int = Field(..., ge=7, le=90, description='Days between transfusions')


class TransfusionPlanUpdate(BaseModel):
    blood_type: Optional[str] = None
    packets_per_transfusion: Optional[int] = Field(None, ge=1, le=10)
    interval_days: Optional[int] = Field(None, ge=7, le=90)
    is_active: Optional[bool] = None


@router.post('/register')
def register_patient(
    profile: PatientProfileCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if db.query(models.PatientProfile).filter(models.PatientProfile.user_id == current_user.id).first():
        raise HTTPException(400, 'Patient profile already exists')
    patient = models.PatientProfile(
        user_id=current_user.id,
        blood_type='',
        age=profile.age,
        city=profile.city,
        state=profile.state,
        hplc_unique_id=profile.hplc_unique_id,
    )
    db.add(patient)
    db.commit()
    db.refresh(patient)
    return {
        'patient_id': patient.id,
        'message': 'Profile created. Please create your transfusion plan next.',
    }


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
    return plan


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
    return {'profile': patient, 'plan': plan}


@router.get('/my-requests')
def get_my_requests(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    patient = db.query(models.PatientProfile).filter(models.PatientProfile.user_id == current_user.id).first()
    if not patient:
        raise HTTPException(404, 'Patient profile not found')
    return db.query(models.TransfusionRequest).filter(
        models.TransfusionRequest.patient_id == patient.id
    ).order_by(models.TransfusionRequest.created_at.desc()).all()
