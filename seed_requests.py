import sys, datetime, uuid
sys.path.append(r'c:\Users\vamsi\Desktop\bloodbridge')
from app.models import User, PatientProfile, TransfusionPlan, TransfusionRequest, RequestStatus, UserRole
from app.security import hash_password
from app.database import SessionLocal

db = SessionLocal()
now = datetime.datetime.utcnow()
pwd = hash_password('password')

# Update Vijayawada patient blood type to O+ to match donor pool
vja_patient = db.query(PatientProfile).join(User).filter(User.full_name == 'Vijayawada Patient').first()
if vja_patient:
    vja_patient.blood_type = 'O+'
    print('Updated Vijayawada Patient blood type to O+')

# Fix Bengaluru patient - create plan + request if missing
blr_patient = db.query(PatientProfile).join(User).filter(User.full_name == 'Bengaluru Patient').first()
if blr_patient:
    existing_plan = db.query(TransfusionPlan).filter(TransfusionPlan.patient_id == blr_patient.id).first()
    if not existing_plan:
        blr_plan = TransfusionPlan(
            patient_id=blr_patient.id,
            blood_type='A+',
            packets_per_transfusion=2,
            interval_days=21,
            is_active=True,
            next_due_date=now + datetime.timedelta(days=3),
        )
        db.add(blr_plan)
        db.flush()

        blr_req = TransfusionRequest(
            patient_id=blr_patient.id,
            requested_date=now + datetime.timedelta(days=3),
            window_start=now + datetime.timedelta(days=2),
            window_end=now + datetime.timedelta(days=5),
            status=RequestStatus.pending,
            is_auto=True,
            packets_required=2,
        )
        db.add(blr_req)
        print('Created plan + request for Bengaluru Patient')

# Test patients to create
test_patients = [
    {
        'name': 'Raji Kumari (AB- Critical)',
        'email': 'patient.ab_neg@test.com',
        'blood': 'AB-',
        'hplc': 'TEST-ABN',
        'city': 'Vijayawada',
        'state': 'Andhra Pradesh',
        'lat': 16.52,
        'lon': 80.64,
        'interval': 14,
        'packets': 3,
        'req_days': 1,
    },
    {
        'name': 'Manoj Rao (B- High)',
        'email': 'patient.b_neg@test.com',
        'blood': 'B-',
        'hplc': 'TEST-BN',
        'city': 'Bengaluru',
        'state': 'Karnataka',
        'lat': 12.98,
        'lon': 77.60,
        'interval': 21,
        'packets': 2,
        'req_days': 5,
    },
    {
        'name': 'Sunita Devi (O+ Normal)',
        'email': 'patient.o_plus2@test.com',
        'blood': 'O+',
        'hplc': 'TEST-OP2',
        'city': 'Hyderabad',
        'state': 'Telangana',
        'lat': 17.4210,
        'lon': 78.3477,
        'interval': 28,
        'packets': 1,
        'req_days': 10,
    },
    {
        'name': 'Arun Kumar (O- Universal)',
        'email': 'patient.o_neg@test.com',
        'blood': 'O-',
        'hplc': 'TEST-ON',
        'city': 'Chennai',
        'state': 'Tamil Nadu',
        'lat': 13.0827,
        'lon': 80.2707,
        'interval': 21,
        'packets': 2,
        'req_days': 2,
    },
]

for tp in test_patients:
    existing_user = db.query(User).filter(User.email == tp['email']).first()
    if not existing_user:
        u = User(
            full_name=tp['name'],
            email=tp['email'],
            phone=tp['email'][:20],
            password_hash=pwd,
            role=UserRole.patient,
            latitude=tp['lat'],
            longitude=tp['lon'],
            is_active=True,
        )
        db.add(u)
        db.flush()

        pat = PatientProfile(
            user_id=u.id,
            blood_type=tp['blood'],
            age=30,
            city=tp['city'],
            state=tp['state'],
            hplc_unique_id=tp['hplc'],
            is_admin_verified=True,
            transfusion_interval_days=tp['interval'],
        )
        db.add(pat)
        db.flush()

        plan = TransfusionPlan(
            patient_id=pat.id,
            blood_type=tp['blood'],
            packets_per_transfusion=tp['packets'],
            interval_days=tp['interval'],
            is_active=True,
            next_due_date=now + datetime.timedelta(days=tp['req_days']),
        )
        db.add(plan)
        db.flush()

        req = TransfusionRequest(
            patient_id=pat.id,
            requested_date=now + datetime.timedelta(days=tp['req_days']),
            window_start=now + datetime.timedelta(days=tp['req_days']-1),
            window_end=now + datetime.timedelta(days=tp['req_days']+3),
            status=RequestStatus.pending,
            is_auto=True,
            packets_required=tp['packets'],
        )
        db.add(req)
        print(f"Created: {tp['name']} | {tp['blood']} | due in {tp['req_days']}d")
    else:
        print(f"Skipped (exists): {tp['name']}")

db.commit()
print('\nDone! All requests created.')
print('\nSummary of all pending requests:')
all_reqs = db.query(TransfusionRequest).filter(TransfusionRequest.status == RequestStatus.pending).all()
for r in all_reqs:
    pat = db.query(PatientProfile).filter(PatientProfile.id == r.patient_id).first()
    u = db.query(User).filter(User.id == pat.user_id).first() if pat else None
    print(f'  [{pat.blood_type if pat else "?"}] {u.full_name if u else "?"} | packets={r.packets_required}')
