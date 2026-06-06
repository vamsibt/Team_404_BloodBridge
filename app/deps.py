# app/deps.py  - dependency injection for auth
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from app.database import get_db
from app.security import decode_token
from app import models

security = HTTPBearer()

def get_current_user(
    creds: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
):
    try:
        payload = decode_token(creds.credentials)
        user_id = payload.get('sub')
    except Exception:
        raise HTTPException(status_code=401, detail='Invalid token')
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail='User not found')
    return user

def require_admin(current_user = Depends(get_current_user)):
    if current_user.role.value != 'admin':
        raise HTTPException(status_code=403, detail='Admin only')
    return current_user

def require_hospital_coordinator(current_user = Depends(get_current_user)):
    if current_user.role.value not in ['admin', 'hospital_coordinator']:
        raise HTTPException(status_code=403, detail='Hospital coordinator only')
    return current_user
