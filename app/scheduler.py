# app/scheduler.py  - Auto-raise requests when transfusion date approaches
from apscheduler.schedulers.background import BackgroundScheduler
from app.database import SessionLocal
from app import models
from app.services.notification import send_notification
from app.services.plan import schedule_next_request
import datetime

scheduler = BackgroundScheduler()


@scheduler.scheduled_job('interval', hours=6)
def check_upcoming_transfusions():
    db = SessionLocal()
    try:
        today = datetime.datetime.utcnow()
        upcoming_plans = db.query(models.TransfusionPlan).filter(
            models.TransfusionPlan.is_active == True,
            models.TransfusionPlan.next_due_date != None,
            models.TransfusionPlan.next_due_date <= today + datetime.timedelta(days=5),
            models.TransfusionPlan.next_due_date >= today,
        ).all()

        for plan in upcoming_plans:
            existing = db.query(models.TransfusionRequest).filter(
                models.TransfusionRequest.patient_id == plan.patient_id,
                models.TransfusionRequest.status.in_([
                    models.RequestStatus.pending,
                    models.RequestStatus.approved,
                    models.RequestStatus.assigned,
                ]),
            ).first()
            if existing:
                continue

            patient = db.query(models.PatientProfile).filter(
                models.PatientProfile.id == plan.patient_id
            ).first()
            if not patient:
                continue

            schedule_next_request(db, patient, plan)
            send_notification(
                db, patient.user_id,
                'Time for Transfusion!',
                f'Your transfusion is due soon. {plan.packets_per_transfusion} packet(s) needed.',
            )
            db.commit()
    finally:
        db.close()
