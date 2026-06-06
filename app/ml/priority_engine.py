from typing import Optional


def calculate_priority_score(
    hemoglobin: Optional[float] = None,
    age: Optional[int] = None,
    days_since_last_transfusion: Optional[int] = None,
    urgency_tier: Optional[str] = None,
    medical_notes: Optional[str] = None,
) -> dict:
    score = 0
    reasons = []

    if hemoglobin is not None:
        if hemoglobin < 7.0:
            score += 40
            reasons.append(f'Hemoglobin critically low ({hemoglobin} g/dL)')
        elif hemoglobin < 8.0:
            score += 30
            reasons.append(f'Hemoglobin low ({hemoglobin} g/dL)')
        elif hemoglobin < 9.0:
            score += 20
            reasons.append(f'Hemoglobin below normal ({hemoglobin} g/dL)')

    if days_since_last_transfusion is not None:
        if days_since_last_transfusion > 35:
            score += 25
            reasons.append(f'Last transfusion overdue ({days_since_last_transfusion} days)')
        elif days_since_last_transfusion > 28:
            score += 15
            reasons.append(f'Last transfusion approaching overdue ({days_since_last_transfusion} days)')

    if age is not None and age < 12:
        score += 15
        reasons.append(f'Pediatric patient (age {age})')

    if urgency_tier and str(urgency_tier).upper() == 'CRITICAL':
        score += 20
        reasons.append('Request marked as CRITICAL urgency')

    if medical_notes:
        found = [kw for kw in ['severe', 'critical', 'urgent'] if kw in medical_notes.lower()]
        if found:
            score += 10
            reasons.append(f'Medical notes contain: {", ".join(found)}')

    score = min(score, 100)
    if score >= 80:
        level = 'CRITICAL'
    elif score >= 60:
        level = 'HIGH'
    elif score >= 40:
        level = 'MEDIUM'
    else:
        level = 'LOW'

    return {'priority_score': score, 'priority_level': level, 'reasons': reasons}
