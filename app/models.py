# app/models.py
from sqlalchemy import Column, String, Boolean, Integer, DateTime, ForeignKey, Text, Float, Enum
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID, JSONB
from app.database import Base
import uuid, datetime, enum

def gen_uuid(): return str(uuid.uuid4())

class UserRole(enum.Enum):
    admin = 'admin'
    donor = 'donor'
    patient = 'patient'
    hospital_coordinator = 'hospital_coordinator'

class RequestStatus(enum.Enum):
    pending = 'pending'
    approved = 'approved'
    assigned = 'assigned'
    scheduled = 'scheduled'
    completed = 'completed'
    cancelled = 'cancelled'

class BridgeType(enum.Enum):
    bridge = 'bridge'
    emergency = 'emergency'

# ============ USER ============
class User(Base):
    __tablename__ = 'users'
    id           = Column(UUID, primary_key=True, default=gen_uuid)
    full_name    = Column(String(255), nullable=False)
    email        = Column(String(255), unique=True, nullable=False)
    phone        = Column(String(20), unique=True, nullable=False)
    password_hash= Column(String(255), nullable=False)
    role         = Column(Enum(UserRole), default=UserRole.donor)
    is_verified  = Column(Boolean, default=False)
    is_active    = Column(Boolean, default=True)
    latitude     = Column(Float, nullable=True)
    longitude    = Column(Float, nullable=True)
    created_at   = Column(DateTime, default=datetime.datetime.utcnow)
    donor_profile   = relationship('DonorProfile',   back_populates='user', uselist=False)
    patient_profile = relationship('PatientProfile', back_populates='user', uselist=False)
    chat_messages   = relationship('ChatHistory', back_populates='user')

# ============ DONOR PROFILE ============
class DonorProfile(Base):
    __tablename__ = 'donor_profiles'
    id              = Column(UUID, primary_key=True, default=gen_uuid)
    user_id         = Column(UUID, ForeignKey('users.id'), unique=True)
    blood_type      = Column(String(5), nullable=False)
    age             = Column(Integer)
    weight          = Column(Float)
    gender          = Column(String(10))
    city            = Column(String(100))
    state           = Column(String(100))
    pincode         = Column(String(10))
    latitude        = Column(Float)
    longitude       = Column(Float)
    hplc_doc_url    = Column(String(500))
    hplc_unique_id  = Column(String(100))
    hospital_id     = Column(UUID, ForeignKey('hospitals.id'), nullable=True)
    is_admin_verified = Column(Boolean, default=False)
    donor_type      = Column(Enum(BridgeType), default=BridgeType.bridge)
    availability    = Column(Boolean, default=True)
    total_donations = Column(Integer, default=0)
    last_donated_at = Column(DateTime, nullable=True)
    notes           = Column(Text, nullable=True)
    created_at      = Column(DateTime, default=datetime.datetime.utcnow)
    user            = relationship('User', back_populates='donor_profile')
    hospital        = relationship('Hospital', back_populates='donors')
    bridge_assignments = relationship('BridgeAssignment', back_populates='donor')
    eligibility_logs   = relationship('DonorEligibilityLog', back_populates='donor')

# ============ PATIENT PROFILE ============
class PatientProfile(Base):
    __tablename__ = 'patient_profiles'
    id                 = Column(UUID, primary_key=True, default=gen_uuid)
    user_id            = Column(UUID, ForeignKey('users.id'), unique=True)
    blood_type         = Column(String(5), nullable=True)
    age                = Column(Integer)
    gender             = Column(String(10))
    city               = Column(String(100))
    state              = Column(String(100))
    pincode            = Column(String(10))
    hplc_doc_url       = Column(String(500))
    hplc_unique_id     = Column(String(100))
    is_admin_verified  = Column(Boolean, default=False)
    transfusion_interval_days = Column(Integer, default=21)
    next_transfusion_date     = Column(DateTime, nullable=True)
    thalassemia_type          = Column(String(50))
    guardian_name             = Column(String(255))
    guardian_phone            = Column(String(20))
    notes                     = Column(Text, nullable=True)
    current_bridge_id  = Column(UUID, ForeignKey('bridges.id'), nullable=True)
    hospital_id        = Column(UUID, ForeignKey('hospitals.id'), nullable=True)
    created_at         = Column(DateTime, default=datetime.datetime.utcnow)
    user               = relationship('User', back_populates='patient_profile')
    bridge             = relationship('Bridge', back_populates='patients')
    requests           = relationship('TransfusionRequest', back_populates='patient')
    plan               = relationship('TransfusionPlan', back_populates='patient', uselist=False)
    hospital          = relationship('Hospital', back_populates='patients')

# ============ BRIDGE ============
class Bridge(Base):
    __tablename__ = 'bridges'
    id          = Column(UUID, primary_key=True, default=gen_uuid)
    bridge_code = Column(String(20), unique=True)  # hashed short code
    is_active   = Column(Boolean, default=True)
    created_at  = Column(DateTime, default=datetime.datetime.utcnow)
    patients    = relationship('PatientProfile', back_populates='bridge')
    assignments = relationship('BridgeAssignment', back_populates='bridge')

# ============ BRIDGE ASSIGNMENT ============
class BridgeAssignment(Base):
    __tablename__ = 'bridge_assignments'
    id          = Column(UUID, primary_key=True, default=gen_uuid)
    bridge_id   = Column(UUID, ForeignKey('bridges.id'))
    donor_id    = Column(UUID, ForeignKey('donor_profiles.id'))
    slot_order  = Column(Integer)   # 1-8 for bridge donors, 9-10 for emergency
    donor_type  = Column(Enum(BridgeType), default=BridgeType.bridge)
    current_turn = Column(Boolean, default=False)
    created_at  = Column(DateTime, default=datetime.datetime.utcnow)
    bridge      = relationship('Bridge', back_populates='assignments')
    donor       = relationship('DonorProfile', back_populates='bridge_assignments')

# ============ TRANSFUSION REQUEST ============
class TransfusionRequest(Base):
    __tablename__ = 'transfusion_requests'
    id              = Column(UUID, primary_key=True, default=gen_uuid)
    patient_id      = Column(UUID, ForeignKey('patient_profiles.id'))
    requested_date  = Column(DateTime)
    window_start    = Column(DateTime)
    window_end      = Column(DateTime)
    status          = Column(Enum(RequestStatus), default=RequestStatus.pending)
    assigned_donor_id = Column(UUID, ForeignKey('donor_profiles.id'), nullable=True)
    hospital_id     = Column(UUID, ForeignKey('hospitals.id'), nullable=True)
    appointment_id  = Column(UUID, ForeignKey('appointments.id'), nullable=True)
    is_auto         = Column(Boolean, default=False)  # system generated
    packets_required = Column(Integer, default=1)
    notes           = Column(Text, nullable=True)
    created_at      = Column(DateTime, default=datetime.datetime.utcnow)
    patient         = relationship('PatientProfile', back_populates='requests')
    hospital        = relationship('Hospital', back_populates='requests')

# ============ HOSPITAL ============
class Hospital(Base):
    __tablename__ = 'hospitals'
    id          = Column(UUID, primary_key=True, default=gen_uuid)
    name        = Column(String(255))
    address     = Column(Text)
    city        = Column(String(100))
    state       = Column(String(100))
    pincode     = Column(String(20))
    phone       = Column(String(20))
    email       = Column(String(255))
    latitude    = Column(Float)
    longitude   = Column(Float)
    coordinator_user_id = Column(UUID, ForeignKey('users.id'), nullable=True)
    is_active   = Column(Boolean, default=True)
    requests    = relationship('TransfusionRequest', back_populates='hospital')
    appointments= relationship('Appointment', back_populates='hospital')
    donors      = relationship('DonorProfile', back_populates='hospital')
    patients    = relationship('PatientProfile', back_populates='hospital')

# ============ APPOINTMENT ============
class Appointment(Base):
    __tablename__ = 'appointments'
    id           = Column(UUID, primary_key=True, default=gen_uuid)
    request_id   = Column(UUID, ForeignKey('transfusion_requests.id'))
    hospital_id  = Column(UUID, ForeignKey('hospitals.id'))
    patient_user_id = Column(UUID, ForeignKey('users.id'))
    donor_user_id   = Column(UUID, ForeignKey('users.id'))
    scheduled_at = Column(DateTime)
    status       = Column(String(50), default='pending')
    notes        = Column(Text, nullable=True)
    created_at   = Column(DateTime, default=datetime.datetime.utcnow)
    hospital     = relationship('Hospital', back_populates='appointments')

# ============ COORDINATOR ASSIGNMENT ============
class CoordinatorAssignment(Base):
    __tablename__ = 'coordinator_assignments'
    id              = Column(UUID, primary_key=True, default=gen_uuid)
    request_id      = Column(UUID, ForeignKey('transfusion_requests.id'), unique=True)
    patient_id      = Column(UUID, ForeignKey('patient_profiles.id'))
    donor_id        = Column(UUID, ForeignKey('donor_profiles.id'))
    coordinator_id  = Column(UUID, ForeignKey('users.id'))
    hospital_id     = Column(UUID, ForeignKey('hospitals.id'))
    status          = Column(String(50), default='pending')
    notes           = Column(Text, nullable=True)
    created_at      = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at      = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

# ============ DONOR ELIGIBILITY LOG ============
class DonorEligibilityLog(Base):
    __tablename__ = 'donor_eligibility_logs'
    id              = Column(UUID, primary_key=True, default=gen_uuid)
    donor_id        = Column(UUID, ForeignKey('donor_profiles.id'))
    screening_passed = Column(Boolean)
    responses_json  = Column(JSONB)
    submission_date = Column(DateTime, default=datetime.datetime.utcnow)
    donor           = relationship('DonorProfile', back_populates='eligibility_logs')

# ============ TRANSFUSION PLAN ============
class TransfusionPlan(Base):
    __tablename__ = 'transfusion_plans'
    id                      = Column(UUID, primary_key=True, default=gen_uuid)
    patient_id              = Column(UUID, ForeignKey('patient_profiles.id'), unique=True)
    blood_type              = Column(String(5), nullable=False)
    packets_per_transfusion = Column(Integer, nullable=False, default=1)
    interval_days           = Column(Integer, nullable=False, default=21)
    is_active               = Column(Boolean, default=True)
    next_due_date           = Column(DateTime, nullable=True)
    created_at              = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at              = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    patient                 = relationship('PatientProfile', back_populates='plan')

# ============ CHAT HISTORY ============
class ChatHistory(Base):
    __tablename__ = 'chat_history'
    id               = Column(UUID, primary_key=True, default=gen_uuid)
    user_id          = Column(UUID, ForeignKey('users.id'))
    question         = Column(Text, nullable=False)
    answer           = Column(Text, nullable=False)
    confidence       = Column(Float, nullable=True)
    source_documents = Column(JSONB, nullable=True)
    created_at       = Column(DateTime, default=datetime.datetime.utcnow)
    user             = relationship('User', back_populates='chat_messages')

# ============ NOTIFICATION ============
class Notification(Base):
    __tablename__ = 'notifications'
    id         = Column(UUID, primary_key=True, default=gen_uuid)
    user_id    = Column(UUID, ForeignKey('users.id'))
    title      = Column(String(255))
    message    = Column(Text)
    is_read    = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
