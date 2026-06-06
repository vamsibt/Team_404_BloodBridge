# app/routers/auth.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr
from typing import Optional
from app import models
from app.database import get_db
from app.security import hash_password, verify_password, create_access_token

router = APIRouter()


class RegisterRequest(BaseModel):
    full_name: str
    email: EmailStr
    phone: str
    password: str
    role: str = 'donor'  # donor | patient | hospital_coordinator
    latitude: Optional[float] = None
    longitude: Optional[float] = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


def _user_response(user: models.User) -> dict:
    return {
        'id': user.id,
        'full_name': user.full_name,
        'email': user.email,
        'phone': user.phone,
        'role': user.role.value,
    }


@router.post('/register')
def register(req: RegisterRequest, db: Session = Depends(get_db)):
    if db.query(models.User).filter(models.User.email == req.email).first():
        raise HTTPException(400, 'Email already registered')
    if db.query(models.User).filter(models.User.phone == req.phone).first():
        raise HTTPException(400, 'Phone number already registered')
    user = models.User(
        full_name=req.full_name,
        email=req.email,
        phone=req.phone,
        password_hash=hash_password(req.password),
        role=models.UserRole[req.role],
        latitude=req.latitude,
        longitude=req.longitude,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return {'user': _user_response(user), 'message': 'Registered successfully'}


@router.post('/login')
def login(req: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.email == req.email).first()
    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(401, 'Invalid credentials')
    token = create_access_token({'sub': user.id, 'role': user.role.value})
    return {
        'access_token': token,
        'token_type': 'bearer',
        'user': _user_response(user),
    }
