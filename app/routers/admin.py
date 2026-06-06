# app/routers/admin.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List
from app import models
from app.database import get_db
from app.deps import require_admin
from app.security import hash_bridge_id
from app.services.notification import send_notification
from app.services.geo import find_nearest_hospital
from app.services.bridge import advance_bridge_turn
import datetime, uuid

router = APIRouter()

class BridgeAssignmentRequest(BaseModel):
    patient_id: str
    donor_ids: List[str]        # exactly 8 bridge donors
    emergency_donor_ids: List[str]  # exactly 2 emergency donors

# ---- Dashboard ----
@router.get('/dashboard')
def dashboard(db: Session = Depends(get_db), admin = Depends(require_admin)):
    total_donors   = db.query(models.DonorProfile).count()
    total_patients = db.query(models.PatientProfile).count()
    pending_requests = db.query(models.TransfusionRequest).filter(
        models.TransfusionRequest.status == models.RequestStatus.pending).count()
    pending_verifications = db.query(models.DonorProfile).filter(
        models.DonorProfile.is_admin_verified == False).count()
    return {
        'total_donors': total_donors,
        'total_patients': total_patients,
        'pending_requests': pending_requests,
        'pending_verifications': pending_verifications
    }

# ---- Verify Donor / Patient ----
@router.post('/verify-donor/{donor_id}')
def verify_donor(donor_id: str, db: Session = Depends(get_db), admin = Depends(require_admin)):
    donor = db.query(models.DonorProfile).filter(models.DonorProfile.id == donor_id).first()
    if not donor: raise HTTPException(404, 'Donor not found')
    donor.is_admin_verified = True
    db.commit()
    return {'message': f'Donor {donor_id} verified'}

@router.post('/verify-patient/{patient_id}')
def verify_patient(patient_id: str, db: Session = Depends(get_db), admin = Depends(require_admin)):
    patient = db.query(models.PatientProfile).filter(models.PatientProfile.id == patient_id).first()
    if not patient: raise HTTPException(404, 'Patient not found')
    patient.is_admin_verified = True
    db.commit()
    return {'message': f'Patient {patient_id} verified'}

# ---- Assign Bridge ----
@router.post('/assign-bridge')
def assign_bridge(
    body: BridgeAssignmentRequest,
    db: Session = Depends(get_db),
    admin = Depends(require_admin)
):
    if len(body.donor_ids) != 8:
        raise HTTPException(400, 'Exactly 8 bridge donors required')
    if len(body.emergency_donor_ids) != 2:
        raise HTTPException(400, 'Exactly 2 emergency donors required')

    # Create bridge
    bridge = models.Bridge(
        bridge_code=hash_bridge_id(str(uuid.uuid4()))
    )
    db.add(bridge); db.flush()

    # Assign bridge donors (slots 1-8)
    for i, donor_id in enumerate(body.donor_ids):
        ba = models.BridgeAssignment(
            bridge_id=bridge.id,
            donor_id=donor_id,
            slot_order=i+1,
            donor_type=models.BridgeType.bridge,
            current_turn=(i == 0)
        )
        db.add(ba)

    # Assign emergency donors (slots 9-10)
    for i, donor_id in enumerate(body.emergency_donor_ids):
        ba = models.BridgeAssignment(
            bridge_id=bridge.id,
            donor_id=donor_id,
            slot_order=9+i,
            donor_type=models.BridgeType.emergency,
        )
        db.add(ba)

    # Assign bridge to patient
    patient = db.query(models.PatientProfile).filter(models.PatientProfile.id == body.patient_id).first()
    if not patient: raise HTTPException(404, 'Patient not found')
    patient.current_bridge_id = bridge.id

    # Find nearest hospital and suggest
    hospital = find_nearest_hospital(db, patient.city, patient.state)

    # Approve the pending request
    req = db.query(models.TransfusionRequest).filter(
        models.TransfusionRequest.patient_id == body.patient_id,
        models.TransfusionRequest.status == models.RequestStatus.pending
    ).first()
    plan = db.query(models.TransfusionPlan).filter(models.TransfusionPlan.patient_id == patient.id).first()
    if req:
        req.status = models.RequestStatus.approved
        if hospital:
            req.hospital_id = hospital.id
        if plan:
            req.packets_required = plan.packets_per_transfusion

    db.commit()
    send_notification(db, patient.user_id, 'Bridge Assigned!', f'Your bridge of donors has been assigned. Bridge Code: {bridge.bridge_code}')
    return {'bridge_id': bridge.id, 'bridge_code': bridge.bridge_code, 'hospital_suggested': hospital.name if hospital else None}

# ---- Advance Turn ----
@router.post('/advance-bridge-turn/{bridge_id}')
def advance_bridge_turn_endpoint(bridge_id: str, db: Session = Depends(get_db), admin = Depends(require_admin)):
    slot = advance_bridge_turn(db, bridge_id)
    if slot is None:
        raise HTTPException(404, 'Bridge not found')
    db.commit()
    return {'message': f'Turn advanced to slot {slot}'}

# ---- List pending verifications ----
@router.get('/pending-donors')
def pending_donors(db: Session = Depends(get_db), admin = Depends(require_admin)):
    return db.query(models.DonorProfile).filter(models.DonorProfile.is_admin_verified == False).all()

@router.get('/pending-patients')
def pending_patients(db: Session = Depends(get_db), admin = Depends(require_admin)):
    return db.query(models.PatientProfile).filter(models.PatientProfile.is_admin_verified == False).all()
