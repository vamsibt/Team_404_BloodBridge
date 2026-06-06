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
    donor_ids: List[str]        # up to 8 bridge donors
    emergency_donor_ids: List[str] = []  # up to 2 emergency donors

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

@router.get('/patient/{patient_id}')
def get_patient_details(patient_id: str, db: Session = Depends(get_db), admin = Depends(require_admin)):
    patient = db.query(models.PatientProfile).filter(models.PatientProfile.id == patient_id).first()
    if not patient: raise HTTPException(404, 'Patient not found')
    user = db.query(models.User).filter(models.User.id == patient.user_id).first()
    return {
        'id': patient.id,
        'city': patient.city,
        'state': patient.state,
        'blood_type': patient.blood_type,
        'latitude': user.latitude if user else None,
        'longitude': user.longitude if user else None,
    }

# ---- Assign Bridge ----
@router.post('/assign-bridge')
def assign_bridge(
    body: BridgeAssignmentRequest,
    db: Session = Depends(get_db),
    admin = Depends(require_admin)
):
    if len(body.donor_ids) < 1:
        raise HTTPException(400, 'At least one bridge donor is required')
    if len(body.donor_ids) > 8:
        raise HTTPException(400, 'At most 8 bridge donors are allowed')
    if len(body.emergency_donor_ids) > 2:
        raise HTTPException(400, 'At most 2 emergency donors are allowed')

    all_requested = body.donor_ids + body.emergency_donor_ids
    if len(all_requested) != len(set(all_requested)):
        raise HTTPException(400, 'Duplicate donor IDs are not allowed')

    patient = db.query(models.PatientProfile).filter(models.PatientProfile.id == body.patient_id).first()
    if not patient:
        raise HTTPException(404, 'Patient not found')
    if patient.current_bridge_id:
        raise HTTPException(400, 'Patient already has an active bridge assigned')

    donors = db.query(models.DonorProfile).filter(models.DonorProfile.id.in_(all_requested)).all()
    if len(donors) != len(all_requested):
        found_ids = {donor.id for donor in donors}
        missing = [donor_id for donor_id in all_requested if donor_id not in found_ids]
        raise HTTPException(404, f'Donor(s) not found: {missing}')

    unverified = [donor.id for donor in donors if not donor.is_admin_verified]
    if unverified:
        raise HTTPException(400, f'The following donors are not verified: {unverified}')

    patient_user = db.query(models.User).filter(models.User.id == patient.user_id).first()
    hospital = find_nearest_hospital(
        db,
        patient.city,
        patient.state,
        lat=patient_user.latitude if patient_user else None,
        lon=patient_user.longitude if patient_user else None,
        require_coordinator=True,
    )
    if not hospital:
        raise HTTPException(400, 'No hospital with a registered coordinator is available. Please register a hospital coordinator before assigning a bridge.')

    req = db.query(models.TransfusionRequest).filter(
        models.TransfusionRequest.patient_id == body.patient_id,
        models.TransfusionRequest.status == models.RequestStatus.pending,
    ).first()
    if not req:
        raise HTTPException(400, 'No pending transfusion request found for this patient. Create a plan first.')

    bridge = models.Bridge(
        bridge_code=hash_bridge_id(str(uuid.uuid4()))
    )
    db.add(bridge)
    db.flush()

    for i, donor_id in enumerate(body.donor_ids):
        ba = models.BridgeAssignment(
            bridge_id=bridge.id,
            donor_id=donor_id,
            slot_order=i + 1,
            donor_type=models.BridgeType.bridge,
            current_turn=(i == 0),
        )
        db.add(ba)

    for i, donor_id in enumerate(body.emergency_donor_ids):
        ba = models.BridgeAssignment(
            bridge_id=bridge.id,
            donor_id=donor_id,
            slot_order=9 + i,
            donor_type=models.BridgeType.emergency,
        )
        db.add(ba)

    patient.current_bridge_id = bridge.id
    plan = db.query(models.TransfusionPlan).filter(models.TransfusionPlan.patient_id == patient.id).first()
    req.status = models.RequestStatus.approved
    req.hospital_id = hospital.id
    if plan:
        req.packets_required = plan.packets_per_transfusion

    db.commit()
    send_notification(
        db,
        patient.user_id,
        'Bridge Assigned!',
        f'Your bridge of donors has been assigned. Bridge Code: {bridge.bridge_code}',
    )
    return {
        'bridge_id': bridge.id,
        'bridge_code': bridge.bridge_code,
        'hospital_suggested': hospital.name,
    }

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

# ---- Bridge Management ----
@router.get('/bridges')
def list_bridges(db: Session = Depends(get_db), admin = Depends(require_admin)):
    bridges = db.query(models.Bridge).order_by(models.Bridge.created_at.desc()).all()
    result = []
    for bridge in bridges:
        assignments = db.query(models.BridgeAssignment).filter(
            models.BridgeAssignment.bridge_id == bridge.id
        ).all()
        bridge_slots = [a for a in assignments if a.donor_type == models.BridgeType.bridge]
        emergency_slots = [a for a in assignments if a.donor_type == models.BridgeType.emergency]
        patient = db.query(models.PatientProfile).filter(
            models.PatientProfile.current_bridge_id == bridge.id
        ).first()
        patient_user = None
        if patient:
            patient_user = db.query(models.User).filter(models.User.id == patient.user_id).first()
        result.append({
            'id': bridge.id,
            'bridge_code': bridge.bridge_code,
            'is_active': bridge.is_active,
            'created_at': bridge.created_at,
            'bridge_slots_filled': len(bridge_slots),
            'bridge_slots_total': 8,
            'emergency_slots_filled': len(emergency_slots),
            'emergency_slots_total': 2,
            'patient_id': patient.id if patient else None,
            'patient_name': patient_user.full_name if patient_user else None,
            'patient_blood_type': patient.blood_type if patient else None,
        })
    return result

@router.get('/bridges/{bridge_id}')
def get_bridge_detail(bridge_id: str, db: Session = Depends(get_db), admin = Depends(require_admin)):
    bridge = db.query(models.Bridge).filter(models.Bridge.id == bridge_id).first()
    if not bridge:
        raise HTTPException(404, 'Bridge not found')
    assignments = db.query(models.BridgeAssignment).filter(
        models.BridgeAssignment.bridge_id == bridge.id
    ).order_by(models.BridgeAssignment.slot_order).all()
    patient = db.query(models.PatientProfile).filter(
        models.PatientProfile.current_bridge_id == bridge.id
    ).first()
    patient_user = None
    if patient:
        patient_user = db.query(models.User).filter(models.User.id == patient.user_id).first()

    slots = []
    for a in assignments:
        donor = db.query(models.DonorProfile).filter(models.DonorProfile.id == a.donor_id).first()
        donor_user = db.query(models.User).filter(models.User.id == donor.user_id).first() if donor else None
        slots.append({
            'slot_order': a.slot_order,
            'donor_type': a.donor_type.value,
            'current_turn': a.current_turn,
            'donor_id': a.donor_id,
            'donor_name': donor_user.full_name if donor_user else None,
            'donor_blood_type': donor.blood_type if donor else None,
        })

    return {
        'id': bridge.id,
        'bridge_code': bridge.bridge_code,
        'is_active': bridge.is_active,
        'created_at': bridge.created_at,
        'patient_id': patient.id if patient else None,
        'patient_name': patient_user.full_name if patient_user else None,
        'patient_city': patient.city if patient else None,
        'patient_state': patient.state if patient else None,
        'patient_blood_type': patient.blood_type if patient else None,
        'patient_latitude': patient_user.latitude if patient_user else None,
        'patient_longitude': patient_user.longitude if patient_user else None,
        'slots': slots,
    }

class AddDonorToBridgeRequest(BaseModel):
    donor_id: str
    donor_type: str = 'bridge'  # 'bridge' or 'emergency'

@router.post('/bridges/{bridge_id}/add-donor')
def add_donor_to_bridge(
    bridge_id: str,
    body: AddDonorToBridgeRequest,
    db: Session = Depends(get_db),
    admin = Depends(require_admin)
):
    bridge = db.query(models.Bridge).filter(models.Bridge.id == bridge_id).first()
    if not bridge:
        raise HTTPException(404, 'Bridge not found')

    # Check donor exists and verified
    donor = db.query(models.DonorProfile).filter(models.DonorProfile.id == body.donor_id).first()
    if not donor:
        raise HTTPException(404, 'Donor not found')
    if not donor.is_admin_verified:
        raise HTTPException(400, 'Donor is not verified')

    # Check donor not already in this bridge
    existing = db.query(models.BridgeAssignment).filter(
        models.BridgeAssignment.bridge_id == bridge_id,
        models.BridgeAssignment.donor_id == body.donor_id,
    ).first()
    if existing:
        raise HTTPException(400, 'Donor is already in this bridge')

    # Check capacity
    dtype = models.BridgeType.bridge if body.donor_type == 'bridge' else models.BridgeType.emergency
    current_slots = db.query(models.BridgeAssignment).filter(
        models.BridgeAssignment.bridge_id == bridge_id,
        models.BridgeAssignment.donor_type == dtype,
    ).count()
    max_slots = 8 if dtype == models.BridgeType.bridge else 2
    if current_slots >= max_slots:
        raise HTTPException(400, f'{"Bridge" if dtype == models.BridgeType.bridge else "Emergency"} slots are full ({max_slots}/{max_slots})')

    # Assign next slot order
    next_order = current_slots + 1 if dtype == models.BridgeType.bridge else 9 + current_slots
    ba = models.BridgeAssignment(
        bridge_id=bridge_id,
        donor_id=body.donor_id,
        slot_order=next_order,
        donor_type=dtype,
        current_turn=False,
    )
    db.add(ba)
    db.commit()
    return {'message': 'Donor added to bridge', 'slot_order': next_order}

