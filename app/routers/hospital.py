# app/routers/hospital.py  - Hospital Coordinator actions
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
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

class HospitalRegistration(BaseModel):
    name: str
    address: str
    city: str
    state: str
    pincode: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    phone: Optional[str] = None
    email: Optional[str] = None

@router.get('/me')
def get_my_hospital(
    db: Session = Depends(get_db),
    coordinator = Depends(require_hospital_coordinator)
):
    hospital = db.query(models.Hospital).filter(
        models.Hospital.coordinator_user_id == coordinator.id
    ).first()
    if not hospital:
        return {'hospital': None}
    return {
        'hospital': {
            'id': hospital.id,
            'name': hospital.name,
            'address': hospital.address,
            'city': hospital.city,
            'state': hospital.state,
            'pincode': hospital.pincode,
            'latitude': hospital.latitude,
            'longitude': hospital.longitude,
            'phone': hospital.phone,
            'email': hospital.email,
            'is_active': hospital.is_active,
        }
    }

@router.post('/me')
def register_or_update_hospital(
    body: HospitalRegistration,
    db: Session = Depends(get_db),
    coordinator = Depends(require_hospital_coordinator)
):
    hospital = db.query(models.Hospital).filter(
        models.Hospital.coordinator_user_id == coordinator.id
    ).first()
    if not hospital:
        hospital = models.Hospital(
            coordinator_user_id=coordinator.id,
            name=body.name,
            address=body.address,
            city=body.city,
            state=body.state,
            pincode=body.pincode,
            latitude=body.latitude,
            longitude=body.longitude,
            phone=body.phone,
            email=body.email,
        )
        db.add(hospital)
    else:
        for field, value in body.model_dump(exclude_unset=True).items():
            setattr(hospital, field, value)
    db.commit()
    db.refresh(hospital)
    return {'hospital_id': hospital.id, 'message': 'Hospital details saved'}

@router.get('/list')
def list_hospitals(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    hospitals = db.query(models.Hospital).filter(models.Hospital.is_active == True).all()
    return [
        {
            'id': h.id,
            'name': h.name,
            'address': h.address,
            'city': h.city,
            'state': h.state,
            'pincode': h.pincode,
            'latitude': h.latitude,
            'longitude': h.longitude,
            'phone': h.phone,
            'email': h.email,
        }
        for h in hospitals
    ]

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
    result = []
    for req in reqs:
        assignment = db.query(models.CoordinatorAssignment).filter(
            models.CoordinatorAssignment.request_id == req.id
        ).first()
        result.append({
            'id': req.id,
            'patient_id': req.patient_id,
            'assigned_donor_id': req.assigned_donor_id,
            'status': req.status.value,
            'requested_date': req.requested_date,
            'packets_required': req.packets_required,
            'coordinator_assignment_id': assignment.id if assignment else None,
        })
    return result

@router.post('/create-appointment')
def create_appointment(
    body: AppointmentCreate,
    db: Session = Depends(get_db),
    coordinator = Depends(require_hospital_coordinator)
):
    req = db.query(models.TransfusionRequest).filter(models.TransfusionRequest.id == body.request_id).first()
    if not req:
        raise HTTPException(404, 'Request not found')
    hospital = db.query(models.Hospital).filter(
        models.Hospital.coordinator_user_id == coordinator.id
    ).first()
    if not hospital:
        raise HTTPException(404, 'No hospital assigned')
    if req.hospital_id and req.hospital_id != hospital.id:
        raise HTTPException(403, 'Request is not assigned to your hospital')
    if req.status != models.RequestStatus.assigned:
        raise HTTPException(400, 'Only assigned requests can be scheduled')
    if not req.assigned_donor_id:
        raise HTTPException(400, 'Request must have an assigned donor before scheduling')

    patient_profile = db.query(models.PatientProfile).filter(models.PatientProfile.id == req.patient_id).first()
    if not patient_profile:
        raise HTTPException(400, 'Patient profile not found for this request')
    donor_profile = db.query(models.DonorProfile).filter(models.DonorProfile.id == req.assigned_donor_id).first()
    if not donor_profile:
        raise HTTPException(400, 'Donor profile not found for this request')

    appointment = models.Appointment(
        request_id=req.id,
        hospital_id=hospital.id,
        patient_user_id=patient_profile.user_id,
        donor_user_id=donor_profile.user_id,
        scheduled_at=datetime.datetime.fromisoformat(body.scheduled_at),
        notes=body.notes,
    )
    db.add(appointment)
    db.flush()
    req.status = models.RequestStatus.scheduled
    req.appointment_id = appointment.id

    coord_assignment = db.query(models.CoordinatorAssignment).filter(
        models.CoordinatorAssignment.request_id == req.id
    ).first()
    if coord_assignment:
        coord_assignment.status = 'scheduled'

    db.commit()
    db.refresh(appointment)
    send_notification(
        db,
        patient_profile.user_id,
        'Appointment Confirmed!',
        f'Your blood transfusion appointment is on {body.scheduled_at}',
    )
    send_notification(
        db,
        donor_profile.user_id,
        'Donation Appointment!',
        f'Please come for donation on {body.scheduled_at}',
    )
    return {'appointment_id': appointment.id, 'message': 'Appointment created'}
