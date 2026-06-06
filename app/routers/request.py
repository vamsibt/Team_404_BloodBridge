# app/routers/request.py  - Transfusion Request lifecycle
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app import models
from app.database import get_db
from app.deps import get_current_user, require_admin
from app.services.notification import send_notification
from app.services.bridge import advance_bridge_turn, get_current_turn_donor
from app.services.plan import schedule_next_request
import datetime

router = APIRouter()


@router.get('/all')
def get_all_requests(
    status: str = None,
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    q = db.query(models.TransfusionRequest)
    if status:
        q = q.filter(models.TransfusionRequest.status == models.RequestStatus[status])
    return q.order_by(models.TransfusionRequest.created_at.desc()).all()


@router.get('/{request_id}')
def get_request(request_id: str, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    req = db.query(models.TransfusionRequest).filter(models.TransfusionRequest.id == request_id).first()
    if not req:
        raise HTTPException(404, 'Request not found')
    return req


@router.post('/{request_id}/complete')
def mark_complete(request_id: str, db: Session = Depends(get_db), admin=Depends(require_admin)):
    req = db.query(models.TransfusionRequest).filter(models.TransfusionRequest.id == request_id).first()
    if not req:
        raise HTTPException(404, 'Not found')
    req.status = models.RequestStatus.completed

    if req.assigned_donor_id:
        donor = db.query(models.DonorProfile).filter(models.DonorProfile.id == req.assigned_donor_id).first()
        if donor:
            donor.total_donations += 1
            donor.last_donated_at = datetime.datetime.utcnow()

    patient = db.query(models.PatientProfile).filter(models.PatientProfile.id == req.patient_id).first()
    plan = db.query(models.TransfusionPlan).filter(models.TransfusionPlan.patient_id == patient.id).first()

    if patient and patient.current_bridge_id:
        advance_bridge_turn(db, patient.current_bridge_id)

    if plan and plan.is_active:
        plan.next_due_date = datetime.datetime.utcnow() + datetime.timedelta(days=plan.interval_days)
        patient.next_transfusion_date = plan.next_due_date
        patient.transfusion_interval_days = plan.interval_days

    db.commit()

    if patient and plan and plan.is_active:
        auto_req = schedule_next_request(db, patient, plan, hospital_id=req.hospital_id)
        if auto_req and patient.current_bridge_id:
            turn_donor = get_current_turn_donor(db, patient.current_bridge_id)
            if turn_donor:
                auto_req.assigned_donor_id = turn_donor.id
        db.commit()
        send_notification(
            db, patient.user_id,
            'Next Transfusion Scheduled',
            f'Your next transfusion is due around {plan.next_due_date.date()}. {plan.packets_per_transfusion} packet(s) required.',
        )

    return {'message': 'Marked complete'}
