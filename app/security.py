# app/security.py
from passlib.context import CryptContext
from jose import JWTError, jwt
from datetime import datetime, timedelta
from app.config import settings
import hashlib

pwd_context = CryptContext(schemes=['argon2'], deprecated='auto')

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)

def create_access_token(data: dict) -> str:
    from uuid import UUID
    to_encode = data.copy()
    # Convert any UUID objects to strings for JSON serialization
    for key, value in to_encode.items():
        if isinstance(value, UUID):
            to_encode[key] = str(value)
    expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({'exp': expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

def decode_token(token: str):
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])

def hash_bridge_id(raw_id: str) -> str:
    return 'BB-' + hashlib.sha256(raw_id.encode()).hexdigest()[:8].upper()
