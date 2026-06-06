-- init.sql  (matches Dataset.csv schema + full app schema)
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TYPE user_role AS ENUM ('admin','donor','patient','hospital_coordinator');
CREATE TYPE request_status AS ENUM ('pending','approved','assigned','scheduled','completed','cancelled');
CREATE TYPE bridge_type AS ENUM ('bridge','emergency');

CREATE TABLE users (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    full_name     VARCHAR(255) NOT NULL,
    email         VARCHAR(255) UNIQUE NOT NULL,
    phone         VARCHAR(20) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    role          user_role DEFAULT 'donor',
    is_verified   BOOLEAN DEFAULT FALSE,
    is_active     BOOLEAN DEFAULT TRUE,
    created_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE donor_profiles (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id           UUID REFERENCES users(id) ON DELETE CASCADE,
    blood_type        VARCHAR(5) NOT NULL,
    age               INTEGER,
    weight            NUMERIC(5,2),
    city              VARCHAR(100),
    state             VARCHAR(100),
    latitude          NUMERIC(10,7),
    longitude         NUMERIC(10,7),
    hplc_doc_url      VARCHAR(500),
    hplc_unique_id    VARCHAR(100),
    is_admin_verified BOOLEAN DEFAULT FALSE,
    donor_type        bridge_type DEFAULT 'bridge',
    availability      BOOLEAN DEFAULT TRUE,
    total_donations   INTEGER DEFAULT 0,
    last_donated_at   TIMESTAMPTZ,
    created_at        TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE patient_profiles (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id           UUID REFERENCES users(id) ON DELETE CASCADE,
    blood_type        VARCHAR(5) NOT NULL,
    age               INTEGER,
    city              VARCHAR(100),
    state             VARCHAR(100),
    hplc_doc_url      VARCHAR(500),
    hplc_unique_id    VARCHAR(100),
    is_admin_verified BOOLEAN DEFAULT FALSE,
    transfusion_interval_days INTEGER DEFAULT 21,
    next_transfusion_date     TIMESTAMPTZ,
    current_bridge_id UUID,
    created_at        TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE bridges (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    bridge_code VARCHAR(20) UNIQUE,
    is_active   BOOLEAN DEFAULT TRUE,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE patient_profiles ADD CONSTRAINT fk_bridge FOREIGN KEY (current_bridge_id) REFERENCES bridges(id);

CREATE TABLE bridge_assignments (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    bridge_id    UUID REFERENCES bridges(id) ON DELETE CASCADE,
    donor_id     UUID REFERENCES donor_profiles(id),
    slot_order   INTEGER,
    donor_type   bridge_type DEFAULT 'bridge',
    current_turn BOOLEAN DEFAULT FALSE,
    created_at   TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE transfusion_requests (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id        UUID REFERENCES patient_profiles(id),
    requested_date    TIMESTAMPTZ,
    window_start      TIMESTAMPTZ,
    window_end        TIMESTAMPTZ,
    status            request_status DEFAULT 'pending',
    assigned_donor_id UUID REFERENCES donor_profiles(id),
    hospital_id       UUID,
    appointment_id    UUID,
    is_auto           BOOLEAN DEFAULT FALSE,
    packets_required  INTEGER DEFAULT 1,
    notes             TEXT,
    created_at        TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE hospitals (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name                 VARCHAR(255),
    address              TEXT,
    city                 VARCHAR(100),
    state                VARCHAR(100),
    latitude             NUMERIC(10,7),
    longitude            NUMERIC(10,7),
    coordinator_user_id  UUID REFERENCES users(id),
    is_active            BOOLEAN DEFAULT TRUE
);

CREATE TABLE appointments (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id       UUID REFERENCES transfusion_requests(id),
    hospital_id      UUID REFERENCES hospitals(id),
    patient_user_id  UUID REFERENCES users(id),
    donor_user_id    UUID REFERENCES users(id),
    scheduled_at     TIMESTAMPTZ,
    status           VARCHAR(50) DEFAULT 'pending',
    notes            TEXT,
    created_at       TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE donor_eligibility_logs (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    donor_id         UUID REFERENCES donor_profiles(id),
    screening_passed BOOLEAN,
    responses_json   JSONB,
    submission_date  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE transfusion_plans (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id              UUID UNIQUE REFERENCES patient_profiles(id) ON DELETE CASCADE,
    blood_type              VARCHAR(5) NOT NULL,
    packets_per_transfusion INTEGER NOT NULL DEFAULT 1,
    interval_days           INTEGER NOT NULL DEFAULT 21,
    is_active               BOOLEAN DEFAULT TRUE,
    next_due_date           TIMESTAMPTZ,
    created_at              TIMESTAMPTZ DEFAULT NOW(),
    updated_at              TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE chat_history (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id          UUID REFERENCES users(id) ON DELETE CASCADE,
    question         TEXT NOT NULL,
    answer           TEXT NOT NULL,
    confidence       NUMERIC(5,2),
    source_documents JSONB,
    created_at       TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_chat_user ON chat_history(user_id);
CREATE INDEX idx_plan_patient ON transfusion_plans(patient_id);

CREATE TABLE notifications (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id    UUID REFERENCES users(id),
    title      VARCHAR(255),
    message    TEXT,
    is_read    BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for performance
CREATE INDEX idx_donor_blood ON donor_profiles(blood_type);
CREATE INDEX idx_donor_city ON donor_profiles(city);
CREATE INDEX idx_donor_verified ON donor_profiles(is_admin_verified);
CREATE INDEX idx_request_status ON transfusion_requests(status);
CREATE INDEX idx_request_patient ON transfusion_requests(patient_id);
CREATE INDEX idx_notif_user ON notifications(user_id);
