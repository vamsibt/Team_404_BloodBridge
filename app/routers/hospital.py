# app/routers/hospital.py  - Hospital Coordinator actions
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from app import models
from app.database import get_db
from app.deps import get_current_user, require_hospital_coordinator
from app.services.notification import send_notification
import datetime

router = APIRouter()

class AppointmentCreate(BaseModel):
    request_id: str
    scheduled_at: str  # ISO datetime
    notes: str = ''

@router.get('/pending-appointments')
def get_pending_appointments(
    db: Session = Depends(get_db),
    coordinator = Depends(require_hospital_coordinator)
):
    # Get hospital this coordinator manages
    hospital = db.query(models.Hospital).filter(
        models.Hospital.coordinator_user_id == coordinator.id).first()
    if not hospital: raise HTTPException(404, 'No hospital assigned')
    reqs = db.query(models.TransfusionRequest).filter(
        models.TransfusionRequest.hospital_id == hospital.id,
        models.TransfusionRequest.status == models.RequestStatus.assigned
    ).all()
    return reqs

@router.post('/create-appointment')
def create_appointment(
    body: AppointmentCreate,
    db: Session = Depends(get_db),
    coordinator = Depends(require_hospital_coordinator)
):
    req = db.query(models.TransfusionRequest).filter(models.TransfusionRequest.id == body.request_id).first()
    if not req: raise HTTPException(404, 'Request not found')
    hospital = db.query(models.Hospital).filter(
        models.Hospital.coordinator_user_id == coordinator.id).first()
    if not hospital:
        raise HTTPException(404, 'No hospital assigned')
    appointment = models.Appointment(
        request_id=req.id,
        hospital_id=hospital.id,
        patient_user_id=db.query(models.PatientProfile).filter(
            models.PatientProfile.id == req.patient_id).first().user_id,
        donor_user_id=db.query(models.DonorProfile).filter(
            models.DonorProfile.id == req.assigned_donor_id).first().user_id if req.assigned_donor_id else None,
        scheduled_at=datetime.datetime.fromisoformat(body.scheduled_at),
        notes=body.notes
    )
    db.add(appointment)
    db.flush()
    req.status = models.RequestStatus.scheduled
    req.appointment_id = appointment.id
    db.commit(); db.refresh(appointment)
    # Notify both patient and donor
    patient_profile = db.query(models.PatientProfile).filter(models.PatientProfile.id == req.patient_id).first()
    send_notification(db, patient_profile.user_id, 'Appointment Confirmed!', f'Your blood transfusion appointment is on {body.scheduled_at}')
    if appointment.donor_user_id:
        send_notification(db, appointment.donor_user_id, 'Donation Appointment!', f'Please come for donation on {body.scheduled_at}')
    return {'appointment_id': appointment.id, 'message': 'Appointment created'}
