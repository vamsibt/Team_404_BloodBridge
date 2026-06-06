-- =============================================================================
--  BLOODBRIDGE — Complete Database Schema + Seed Data
--  PostgreSQL 15+
--  Run: psql -U postgres -d bloodbridge -f init.sql
-- =============================================================================

-- ---------------------------------------------------------------------------
-- 0. EXTENSIONS
-- ---------------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS pgcrypto;    -- gen_random_uuid(), crypt()
CREATE EXTENSION IF NOT EXISTS pg_trgm;     -- trigram search for names/cities
CREATE EXTENSION IF NOT EXISTS unaccent;    -- accent-insensitive search

-- ---------------------------------------------------------------------------
-- 1. ENUM TYPES
-- ---------------------------------------------------------------------------
CREATE TYPE user_role AS ENUM (
    'admin',
    'donor',
    'patient',
    'hospital_coordinator'
);

CREATE TYPE request_status AS ENUM (
    'pending',
    'approved',
    'assigned',
    'scheduled',
    'completed',
    'cancelled'
);

CREATE TYPE bridge_type AS ENUM (
    'bridge',       -- one of the 8 dedicated donors
    'emergency'     -- one of the 2 on-call emergency donors
);

CREATE TYPE appointment_status AS ENUM (
    'pending',
    'confirmed',
    'completed',
    'cancelled',
    'no_show'
);

CREATE TYPE notification_type AS ENUM (
    'transfusion_reminder',
    'appointment_confirmed',
    'donor_turn',
    'admin_action',
    'general'
);

-- ---------------------------------------------------------------------------
-- 2. CORE TABLES
-- ---------------------------------------------------------------------------

-- 2.1 USERS  (all roles share this table)
CREATE TABLE users (
    id            UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    full_name     VARCHAR(255) NOT NULL,
    email         VARCHAR(255) UNIQUE NOT NULL,
    phone         VARCHAR(20)  UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    role          user_role    NOT NULL DEFAULT 'donor',
    is_verified   BOOLEAN      NOT NULL DEFAULT FALSE,
    is_active     BOOLEAN      NOT NULL DEFAULT TRUE,
    profile_photo_url VARCHAR(500),
    preferred_language VARCHAR(10) DEFAULT 'en',   -- for multilingual chatbot
    telegram_chat_id  VARCHAR(50),                  -- for Telegram notifications
    latitude      NUMERIC(10,7),                  -- captured at registration (all roles)
    longitude     NUMERIC(10,7),
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- 2.2 DONOR PROFILES
CREATE TABLE donor_profiles (
    id                  UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID         NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    blood_type          VARCHAR(5)   NOT NULL,
    age                 INTEGER      CHECK (age >= 18 AND age <= 65),
    weight              NUMERIC(5,2) CHECK (weight >= 45),
    gender              VARCHAR(10),
    city                VARCHAR(100),
    state               VARCHAR(100),
    pincode             VARCHAR(10),
    latitude            NUMERIC(10,7),
    longitude           NUMERIC(10,7),
    hplc_doc_url        VARCHAR(500),
    hplc_unique_id      VARCHAR(100) UNIQUE,
    hospital_id         UUID,
    is_admin_verified   BOOLEAN      NOT NULL DEFAULT FALSE,
    donor_type          bridge_type  NOT NULL DEFAULT 'bridge',
    availability        BOOLEAN      NOT NULL DEFAULT TRUE,
    total_donations     INTEGER      NOT NULL DEFAULT 0,
    last_donated_at     TIMESTAMPTZ,
    next_eligible_date  TIMESTAMPTZ,               -- auto-computed after donation
    notes               TEXT,
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- 2.3 PATIENT PROFILES
CREATE TABLE patient_profiles (
    id                        UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                   UUID         NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    blood_type                VARCHAR(5)   NOT NULL,
    age                       INTEGER,
    gender                    VARCHAR(10),
    city                      VARCHAR(100),
    state                     VARCHAR(100),
    pincode                   VARCHAR(10),
    hplc_doc_url              VARCHAR(500),
    hplc_unique_id            VARCHAR(100) UNIQUE,
    is_admin_verified         BOOLEAN      NOT NULL DEFAULT FALSE,
    thalassemia_type          VARCHAR(50),          -- Major / Intermedia / Minor
    transfusion_interval_days INTEGER      NOT NULL DEFAULT 21,
    packets_per_transfusion   INTEGER      NOT NULL DEFAULT 1,
    next_transfusion_date     TIMESTAMPTZ,
    current_bridge_id         UUID,                 -- FK added after bridges table
    hospital_id               UUID,                 -- hospital association (added later as FK)
    guardian_name             VARCHAR(255),
    guardian_phone            VARCHAR(20),
    notes                     TEXT,
    created_at                TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at                TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- 2.4 BRIDGES
CREATE TABLE bridges (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    bridge_code VARCHAR(20) UNIQUE NOT NULL,   -- BB-XXXXXXXX hashed short code
    is_active   BOOLEAN     NOT NULL DEFAULT TRUE,
    created_by  UUID        REFERENCES users(id),
    notes       TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Now add the FK from patient_profiles to bridges
ALTER TABLE patient_profiles
    ADD CONSTRAINT fk_patient_bridge
    FOREIGN KEY (current_bridge_id) REFERENCES bridges(id)
    ON DELETE SET NULL;

-- 2.5 BRIDGE ASSIGNMENTS  (the 8 + 2 slot table)
CREATE TABLE bridge_assignments (
    id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    bridge_id    UUID        NOT NULL REFERENCES bridges(id) ON DELETE CASCADE,
    donor_id     UUID        NOT NULL REFERENCES donor_profiles(id),
    slot_order   INTEGER     NOT NULL CHECK (slot_order BETWEEN 1 AND 10),
                             -- 1-8 = bridge donors, 9-10 = emergency donors
    donor_type   bridge_type NOT NULL DEFAULT 'bridge',
    current_turn BOOLEAN     NOT NULL DEFAULT FALSE,
    donations_in_this_bridge INTEGER NOT NULL DEFAULT 0,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (bridge_id, slot_order),
    UNIQUE (bridge_id, donor_id)
);

-- 2.6 TRANSFUSION REQUESTS
CREATE TABLE transfusion_requests (
    id                  UUID           PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id          UUID           NOT NULL REFERENCES patient_profiles(id),
    requested_date      TIMESTAMPTZ,
    window_start        TIMESTAMPTZ,
    window_end          TIMESTAMPTZ,
    status              request_status NOT NULL DEFAULT 'pending',
    assigned_donor_id   UUID           REFERENCES donor_profiles(id),
    hospital_id         UUID,          -- FK added after hospitals table
    appointment_id      UUID,          -- FK added after appointments table
    is_auto             BOOLEAN        NOT NULL DEFAULT FALSE,
    packets_required    INTEGER        NOT NULL DEFAULT 1,
    priority_score      NUMERIC(5,2),  -- ML model output for urgency scoring
    notes               TEXT,
    created_at          TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ    NOT NULL DEFAULT NOW()
);

-- 2.7 HOSPITALS  (includes blood banks that do transfusions)
CREATE TABLE hospitals (
    id                   UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    name                 VARCHAR(255) NOT NULL,
    short_name           VARCHAR(100),
    hospital_type        VARCHAR(50) DEFAULT 'hospital',  -- hospital | blood_bank | clinic
    address              TEXT,
    city                 VARCHAR(100) NOT NULL,
    state                VARCHAR(100) NOT NULL,
    pincode              VARCHAR(10),
    latitude             NUMERIC(10,7),
    longitude            NUMERIC(10,7),
    phone                VARCHAR(20),
    email                VARCHAR(255),
    coordinator_user_id  UUID        REFERENCES users(id) ON DELETE SET NULL,
    has_blood_bank       BOOLEAN     NOT NULL DEFAULT FALSE,
    accepts_thalassemia  BOOLEAN     NOT NULL DEFAULT TRUE,
    is_active            BOOLEAN     NOT NULL DEFAULT TRUE,
    notes                TEXT,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Now add FKs from transfusion_requests to hospitals
ALTER TABLE transfusion_requests
    ADD CONSTRAINT fk_request_hospital
    FOREIGN KEY (hospital_id) REFERENCES hospitals(id) ON DELETE SET NULL;

-- Add FK from patient_profiles to hospitals
ALTER TABLE patient_profiles
    ADD CONSTRAINT fk_patient_hospital
    FOREIGN KEY (hospital_id) REFERENCES hospitals(id) ON DELETE SET NULL;

-- Add FK from donor_profiles to hospitals
ALTER TABLE donor_profiles
    ADD CONSTRAINT fk_donor_hospital
    FOREIGN KEY (hospital_id) REFERENCES hospitals(id) ON DELETE SET NULL;

-- 2.8 APPOINTMENTS
CREATE TABLE appointments (
    id               UUID               PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id       UUID               REFERENCES transfusion_requests(id),
    hospital_id      UUID               NOT NULL REFERENCES hospitals(id),
    patient_user_id  UUID               NOT NULL REFERENCES users(id),
    donor_user_id    UUID               REFERENCES users(id),
    scheduled_at     TIMESTAMPTZ        NOT NULL,
    status           appointment_status NOT NULL DEFAULT 'pending',
    confirmed_by     UUID               REFERENCES users(id),  -- coordinator who confirmed
    notes            TEXT,
    created_at       TIMESTAMPTZ        NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ        NOT NULL DEFAULT NOW()
);

-- Now add FK from transfusion_requests to appointments
ALTER TABLE transfusion_requests
    ADD CONSTRAINT fk_request_appointment
    FOREIGN KEY (appointment_id) REFERENCES appointments(id) ON DELETE SET NULL;

-- 2.8b COORDINATOR ASSIGNMENTS  (donor accepts → coordinator books appointment)
CREATE TABLE coordinator_assignments (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id      UUID        NOT NULL UNIQUE REFERENCES transfusion_requests(id) ON DELETE CASCADE,
    patient_id      UUID        NOT NULL REFERENCES patient_profiles(id),
    donor_id        UUID        NOT NULL REFERENCES donor_profiles(id),
    coordinator_id  UUID        NOT NULL REFERENCES users(id),
    hospital_id     UUID        NOT NULL REFERENCES hospitals(id),
    status          VARCHAR(50) NOT NULL DEFAULT 'pending',  -- pending | scheduled
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 2.9 DONOR ELIGIBILITY LOGS  (11-question screening from Dataset.csv)
CREATE TABLE donor_eligibility_logs (
    id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    donor_id         UUID        NOT NULL REFERENCES donor_profiles(id) ON DELETE CASCADE,
    screening_passed BOOLEAN     NOT NULL,
    responses_json   JSONB       NOT NULL,
    -- Flattened columns for fast ML feature extraction
    weight_adequate          BOOLEAN,
    age_in_range             BOOLEAN,
    has_low_hemoglobin       BOOLEAN,
    donated_recently         BOOLEAN,
    recent_illness_or_meds   BOOLEAN,
    recent_tattoo_piercing   BOOLEAN,
    recent_surgery_dental    BOOLEAN,
    pregnant_or_breastfeeding BOOLEAN,
    chronic_disease          BOOLEAN,
    blood_disorder           BOOLEAN,
    infectious_disease       BOOLEAN,
    fail_reason              VARCHAR(100),  -- first failing key
    screened_by              VARCHAR(50) DEFAULT 'self_declaration',
    submission_date          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 2.10 TRANSFUSION PLANS  (the master schedule per patient)
CREATE TABLE transfusion_plans (
    id                      UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id              UUID        NOT NULL UNIQUE REFERENCES patient_profiles(id) ON DELETE CASCADE,
    blood_type              VARCHAR(5)  NOT NULL,
    packets_per_transfusion INTEGER     NOT NULL DEFAULT 1,
    interval_days           INTEGER     NOT NULL DEFAULT 21,
    is_active               BOOLEAN     NOT NULL DEFAULT TRUE,
    next_due_date           TIMESTAMPTZ,
    last_updated_by         UUID        REFERENCES users(id),
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 2.11 CHAT HISTORY  (for the RAG chatbot)
CREATE TABLE chat_history (
    id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id          UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_id       VARCHAR(100),               -- group messages into sessions
    role             VARCHAR(20) NOT NULL DEFAULT 'user',  -- user | assistant
    question         TEXT        NOT NULL,
    answer           TEXT        NOT NULL,
    language         VARCHAR(10) DEFAULT 'en',
    confidence       NUMERIC(5,2),
    source_documents JSONB,
    tokens_used      INTEGER,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 2.12 NOTIFICATIONS
CREATE TABLE notifications (
    id                UUID              PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id           UUID              NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    notification_type notification_type NOT NULL DEFAULT 'general',
    title             VARCHAR(255)      NOT NULL,
    message           TEXT              NOT NULL,
    related_request_id UUID             REFERENCES transfusion_requests(id) ON DELETE SET NULL,
    is_read           BOOLEAN           NOT NULL DEFAULT FALSE,
    sent_via_email    BOOLEAN           NOT NULL DEFAULT FALSE,
    sent_via_telegram BOOLEAN           NOT NULL DEFAULT FALSE,
    created_at        TIMESTAMPTZ       NOT NULL DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- 3. INDEXES
-- ---------------------------------------------------------------------------

-- Users
CREATE INDEX idx_users_email       ON users(email);
CREATE INDEX idx_users_phone       ON users(phone);
CREATE INDEX idx_users_role        ON users(role);
CREATE INDEX idx_users_location    ON users(latitude, longitude)
    WHERE latitude IS NOT NULL AND longitude IS NOT NULL;

-- Donor profiles
CREATE INDEX idx_donor_user        ON donor_profiles(user_id);
CREATE INDEX idx_donor_blood       ON donor_profiles(blood_type);
CREATE INDEX idx_donor_city        ON donor_profiles(city);
CREATE INDEX idx_donor_state       ON donor_profiles(state);
CREATE INDEX idx_donor_verified    ON donor_profiles(is_admin_verified);
CREATE INDEX idx_donor_type        ON donor_profiles(donor_type);
CREATE INDEX idx_donor_available   ON donor_profiles(availability) WHERE availability = TRUE;
CREATE INDEX idx_donor_hplc        ON donor_profiles(hplc_unique_id);
-- GIN index for trigram city search
CREATE INDEX idx_donor_city_trgm   ON donor_profiles USING GIN (city gin_trgm_ops);

-- Patient profiles
CREATE INDEX idx_patient_user      ON patient_profiles(user_id);
CREATE INDEX idx_patient_blood     ON patient_profiles(blood_type);
CREATE INDEX idx_patient_city      ON patient_profiles(city);
CREATE INDEX idx_patient_verified  ON patient_profiles(is_admin_verified);
CREATE INDEX idx_patient_bridge    ON patient_profiles(current_bridge_id);
CREATE INDEX idx_patient_next_tx   ON patient_profiles(next_transfusion_date)
    WHERE next_transfusion_date IS NOT NULL;

-- Bridges
CREATE INDEX idx_bridge_code       ON bridges(bridge_code);
CREATE INDEX idx_bridge_active     ON bridges(is_active) WHERE is_active = TRUE;

-- Bridge assignments
CREATE INDEX idx_ba_bridge         ON bridge_assignments(bridge_id);
CREATE INDEX idx_ba_donor          ON bridge_assignments(donor_id);
CREATE INDEX idx_ba_turn           ON bridge_assignments(current_turn) WHERE current_turn = TRUE;

-- Transfusion requests
CREATE INDEX idx_req_patient       ON transfusion_requests(patient_id);
CREATE INDEX idx_req_status        ON transfusion_requests(status);
CREATE INDEX idx_req_hospital      ON transfusion_requests(hospital_id);
CREATE INDEX idx_req_donor         ON transfusion_requests(assigned_donor_id);
CREATE INDEX idx_req_created       ON transfusion_requests(created_at DESC);
CREATE INDEX idx_req_window        ON transfusion_requests(window_start, window_end);

-- Hospitals
CREATE INDEX idx_hosp_city         ON hospitals(city);
CREATE INDEX idx_hosp_state        ON hospitals(state);
CREATE INDEX idx_hosp_active       ON hospitals(is_active) WHERE is_active = TRUE;
CREATE INDEX idx_hosp_type         ON hospitals(hospital_type);
CREATE INDEX idx_hosp_city_trgm    ON hospitals USING GIN (city gin_trgm_ops);

-- Appointments
CREATE INDEX idx_appt_request      ON appointments(request_id);
CREATE INDEX idx_appt_hospital     ON appointments(hospital_id);
CREATE INDEX idx_appt_patient      ON appointments(patient_user_id);
CREATE INDEX idx_appt_donor        ON appointments(donor_user_id);
CREATE INDEX idx_appt_scheduled    ON appointments(scheduled_at);
CREATE INDEX idx_appt_status       ON appointments(status);

-- Coordinator assignments
CREATE INDEX idx_coord_request     ON coordinator_assignments(request_id);
CREATE INDEX idx_coord_coordinator ON coordinator_assignments(coordinator_id);
CREATE INDEX idx_coord_hospital    ON coordinator_assignments(hospital_id);
CREATE INDEX idx_coord_status      ON coordinator_assignments(status) WHERE status = 'pending';

-- Eligibility logs
CREATE INDEX idx_elig_donor        ON donor_eligibility_logs(donor_id);
CREATE INDEX idx_elig_passed       ON donor_eligibility_logs(screening_passed);
CREATE INDEX idx_elig_date         ON donor_eligibility_logs(submission_date DESC);

-- Transfusion plans
CREATE INDEX idx_plan_patient      ON transfusion_plans(patient_id);
CREATE INDEX idx_plan_next_due     ON transfusion_plans(next_due_date)
    WHERE next_due_date IS NOT NULL;

-- Chat history
CREATE INDEX idx_chat_user         ON chat_history(user_id);
CREATE INDEX idx_chat_session      ON chat_history(session_id);
CREATE INDEX idx_chat_created      ON chat_history(created_at DESC);

-- Notifications
CREATE INDEX idx_notif_user        ON notifications(user_id);
CREATE INDEX idx_notif_unread      ON notifications(user_id, is_read) WHERE is_read = FALSE;
CREATE INDEX idx_notif_created     ON notifications(created_at DESC);

-- ---------------------------------------------------------------------------
-- 4. HELPER FUNCTION — auto-update updated_at
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_donor_updated_at
    BEFORE UPDATE ON donor_profiles
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_patient_updated_at
    BEFORE UPDATE ON patient_profiles
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_req_updated_at
    BEFORE UPDATE ON transfusion_requests
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_appt_updated_at
    BEFORE UPDATE ON appointments
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_coord_updated_at
    BEFORE UPDATE ON coordinator_assignments
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_plan_updated_at
    BEFORE UPDATE ON transfusion_plans
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------------
-- 7. COMMENTS ON KEY DESIGN DECISIONS
-- ---------------------------------------------------------------------------
COMMENT ON COLUMN bridge_assignments.slot_order IS
    'Slots 1-8 are bridge donors; slots 9-10 are emergency donors. current_turn=TRUE marks whose turn it is to donate.';

COMMENT ON COLUMN patient_profiles.transfusion_interval_days IS
    'Patient-specific interval between transfusions. The 3-day selection window is: (next_transfusion_date - 2 days) to next_transfusion_date.';

COMMENT ON COLUMN transfusion_requests.priority_score IS
    'Output from ML priority prediction model (0-100). Higher = more urgent. Used by admin to queue requests.';

COMMENT ON COLUMN donor_eligibility_logs.screened_by IS
    'self_declaration | admin | ml_model — who performed the screening assessment.';

COMMENT ON COLUMN hospitals.hospital_type IS
    'hospital | blood_bank | clinic — drives search and display logic.';

COMMENT ON TABLE transfusion_plans IS
    'Master schedule per patient. Drives the APScheduler job that auto-raises requests 5 days before next_due_date.';

COMMENT ON TABLE chat_history IS
    'Full conversation log for the RAG chatbot. session_id groups a chat session. Used for chatbot memory and admin audit.';