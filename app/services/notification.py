# app/services/notification.py
from sqlalchemy.orm import Session
from app import models
import aiosmtplib
from email.message import EmailMessage
from app.config import settings

def send_notification(db: Session, user_id: str, title: str, message: str):
    notif = models.Notification(
        user_id=user_id,
        title=title,
        message=message
    )
    db.add(notif)
    db.commit()

async def send_email(to_email: str, subject: str, body: str):
    message = EmailMessage()
    message['From'] = settings.SMTP_USER
    message['To'] = to_email
    message['Subject'] = subject
    message.set_content(body)
    async with aiosmtplib.SMTP(hostname=settings.SMTP_HOST, port=settings.SMTP_PORT) as smtp:
        await smtp.login(settings.SMTP_USER, settings.SMTP_PASS)
        await smtp.send_message(message)
