# app/services/geo.py  - Find nearest hospital
from sqlalchemy.orm import Session
from app import models
import math

def haversine(lat1, lon1, lat2, lon2):
    R = 6371  # Earth radius km
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return R * 2 * math.asin(math.sqrt(a))

def find_nearest_hospital(db: Session, city: str, state: str, lat: float = None, lon: float = None):
    hospitals = db.query(models.Hospital).filter(
        models.Hospital.is_active == True
    ).all()
    if not hospitals: return None
    # Try city match first
    city_match = [h for h in hospitals if h.city.lower() == city.lower()]
    if city_match:
        if lat and lon:
            return min(city_match, key=lambda h: haversine(lat, lon, h.latitude or 0, h.longitude or 0))
        return city_match[0]
    # State match fallback
    state_match = [h for h in hospitals if h.state.lower() == state.lower()]
    return state_match[0] if state_match else hospitals[0]
