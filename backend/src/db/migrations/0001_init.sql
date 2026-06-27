-- M1 schema: users, consents, devices, refresh tokens.
-- Later milestones add codeword_meta, guardianships, recordings, access logs.

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- A SafeWord account. `apple_subject` is the stable Apple user identifier
-- ("sub" claim) from Sign in with Apple. Email may be absent/relayed.
CREATE TABLE IF NOT EXISTS users (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    apple_subject  TEXT UNIQUE NOT NULL,
    email          TEXT,
    display_name   TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Logged consent (Constraint 2). One row per accepted consent version so we
-- keep the full history; the app re-gates when ConsentVersion is bumped.
CREATE TABLE IF NOT EXISTS consents (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id           UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    version           TEXT NOT NULL,
    acknowledged      JSONB NOT NULL,          -- which clauses were affirmed
    accepted_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, version)
);

-- APNs device tokens for push fan-out (used from M6; modelled now).
CREATE TABLE IF NOT EXISTS devices (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    apns_token    TEXT NOT NULL,
    platform      TEXT NOT NULL DEFAULT 'ios',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, apns_token)
);

-- Rotating refresh tokens. We store only a SHA-256 hash, never the raw token.
CREATE TABLE IF NOT EXISTS refresh_tokens (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash   TEXT UNIQUE NOT NULL,
    expires_at   TIMESTAMPTZ NOT NULL,
    revoked_at   TIMESTAMPTZ,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_refresh_tokens_user ON refresh_tokens(user_id);
CREATE INDEX IF NOT EXISTS idx_consents_user ON consents(user_id);
CREATE INDEX IF NOT EXISTS idx_devices_user ON devices(user_id);
