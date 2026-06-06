import datetime
from sqlalchemy.orm import Session
from app import models


def schedule_first_request(db: Session, patient: models.PatientProfile, plan: models.TransfusionPlan):
    due = datetime.datetime.utcnow() + datetime.timedelta(days=plan.interval_days)
    req = models.TransfusionRequest(
        patient_id=patient.id,
        requested_date=due,
        packets_required=plan.packets_per_transfusion,
        window_start=due - datetime.timedelta(days=2),
        window_end=due,
        status=models.RequestStatus.pending,
        is_auto=False,
    )
    plan.next_due_date = due
    patient.blood_type = plan.blood_type
    patient.transfusion_interval_days = plan.interval_days
    patient.next_transfusion_date = due
    db.add(req)


def schedule_next_request(db: Session, patient: models.PatientProfile, plan: models.TransfusionPlan, hospital_id=None):
    if not plan.is_active:
        return None
    due = plan.next_due_date or (
        datetime.datetime.utcnow() + datetime.timedelta(days=plan.interval_days)
    )
    req = models.TransfusionRequest(
        patient_id=patient.id,
        requested_date=due,
        packets_required=plan.packets_per_transfusion,
        window_start=due - datetime.timedelta(days=2),
        window_end=due,
        status=models.RequestStatus.approved,
        is_auto=True,
        hospital_id=hospital_id,
    )
    db.add(req)
    return req


def sync_plan_to_patient(patient: models.PatientProfile, plan: models.TransfusionPlan):
    patient.blood_type = plan.blood_type
    patient.transfusion_interval_days = plan.interval_days
    if plan.next_due_date:
        patient.next_transfusion_date = plan.next_due_date
