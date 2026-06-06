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

def find_nearest_hospital(db: Session, city: str, state: str, lat: float = None, lon: float = None, require_coordinator: bool = False):
    q = db.query(models.Hospital).filter(models.Hospital.is_active == True)
    if require_coordinator:
        q = q.filter(models.Hospital.coordinator_user_id.isnot(None))
    hospitals = q.all()
    if not hospitals:
        return None

    def score(hospital):
        if lat is not None and lon is not None and hospital.latitude is not None and hospital.longitude is not None:
            return haversine(lat, lon, hospital.latitude, hospital.longitude)
        return float('inf')

    def select_best(candidates):
        if lat is not None and lon is not None:
            return min(candidates, key=score)
        return candidates[0]

    city_match = [h for h in hospitals if h.city and h.city.lower() == city.lower()]
    if city_match:
        return select_best(city_match)
    state_match = [h for h in hospitals if h.state and h.state.lower() == state.lower()]
    if state_match:
        return select_best(state_match)
    return select_best(hospitals)


def donor_distance_km(donor, patient_lat: float, patient_lon: float, db: Session = None) -> float:
    """Distance from patient to donor using donor profile coords, then user coords."""
    lat = donor.latitude
    lon = donor.longitude
    if lat is None or lon is None:
        user = getattr(donor, 'user', None)
        if user is None and db is not None:
            user = db.query(models.User).filter(models.User.id == donor.user_id).first()
        if user and user.latitude is not None and user.longitude is not None:
            lat, lon = user.latitude, user.longitude
        else:
            return 9999.0
    return haversine(patient_lat, patient_lon, lat, lon)
