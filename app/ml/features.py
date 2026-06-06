import datetime
from app import models
from app.ml.model_loader import BLOOD_GROUP_MAP


def donor_availability_features(donor: models.DonorProfile) -> dict:
    now = datetime.datetime.utcnow()
    tenure_days = max((now - (donor.created_at or now)).days, 1)
    last_donation_days = (
        (now - donor.last_donated_at).days if donor.last_donated_at else 365
    )
    return {
        'days_since_last_contact': min(last_donation_days, 400),
        'days_since_last_donation': last_donation_days,
        'days_until_eligible': max(90 - last_donation_days, -30),
        'donor_tenure_days': tenure_days,
        'blood_group_encoded': BLOOD_GROUP_MAP.get(donor.blood_type, 0),
        'gender_encoded': 0,
        'role_encoded': 0 if donor.donor_type == models.BridgeType.bridge else 1,
        'donor_type_encoded': 0,
        'frequency_in_days_clean': 90,
        'cycle_of_donations_clean': min(donor.total_donations, 5),
        'contact_recency_ratio': min(last_donation_days / tenure_days, 1.0),
        'donation_recency_ratio': min(last_donation_days / tenure_days, 1.0),
        'eligible_soon': 1 if last_donation_days >= 60 else 0,
        'long_tenure': 1 if tenure_days > 365 else 0,
        'is_assigned_to_bridge': 1 if donor.bridge_assignments else 0,
    }


def donor_churn_features(donor: models.DonorProfile) -> dict:
    now = datetime.datetime.utcnow()
    tenure_days = max((now - (donor.created_at or now)).days, 1)
    last_donation_days = (
        (now - donor.last_donated_at).days if donor.last_donated_at else 365
    )
    role_encoded = 0 if donor.donor_type == models.BridgeType.bridge else 1
    return {
        'days_until_eligible': max(90 - last_donation_days, -30),
        'donor_tenure_days': tenure_days,
        'blood_group_encoded': BLOOD_GROUP_MAP.get(donor.blood_type, 0),
        'gender_encoded': 0,
        'role_encoded': role_encoded,
        'donor_type_encoded': 0,
        'cycle_of_donations_clean': min(donor.total_donations, 5),
        'latitude_clean': donor.latitude or 17.4,
        'longitude_clean': donor.longitude or 78.5,
        'is_bridge_donor': 1 if role_encoded == 0 else 0,
        'is_emergency_donor': 1 if role_encoded == 1 else 0,
        'is_regular_donor': 1,
        'tenure_years': tenure_days / 365.0,
        'has_long_cycle': 1 if donor.total_donations > 3 else 0,
        'eligible_soon': 1 if last_donation_days >= 60 else 0,
        'is_assigned_to_bridge': 1 if donor.bridge_assignments else 0,
    }


def request_priority_features(patient, plan, assigned_count: int = 0) -> dict:
    blood_type = plan.blood_type if plan else patient.blood_type
    rarity_map = {'O+': 1, 'A+': 1, 'B+': 2, 'AB+': 3, 'O-': 3, 'A-': 4, 'B-': 4, 'AB-': 5}
    return {
        'blood_group_encoded': BLOOD_GROUP_MAP.get(blood_type, 0),
        'gender_encoded': 0,
        'blood_rarity': rarity_map.get(blood_type, 2),
        'num_assigned_donors': assigned_count,
        'num_active_donors': max(assigned_count - 1, 0),
        'num_eligible_donors': assigned_count,
        'total_donor_calls': 0,
        'latitude_clean': 17.4,
        'longitude_clean': 78.5,
    }


CHURN_LABELS = {0: 'HIGH_RISK', 1: 'LOW_RISK', 2: 'MEDIUM_RISK'}
PRIORITY_LABELS = {0: 'CRITICAL', 1: 'HIGH', 2: 'LOW', 3: 'MEDIUM'}
AVAILABILITY_LABELS = {0: "Won't Donate", 1: 'Will Donate'}
