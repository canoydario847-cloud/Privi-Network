-- Dedicated Privi Universe session database ONLY.
-- Administrator-reviewed migration; never run on billing or ledger databases.
-- Execute with a migrations role after verifying database name, backups,
-- SSL certificate, secret storage, security and ownership boundaries.
CREATE SCHEMA IF NOT EXISTS privi_sessions;
CREATE TABLE IF NOT EXISTS privi_sessions.sessions (
    handle_hash BYTEA PRIMARY KEY CHECK (octet_length(handle_hash) = 32),
    subject TEXT NOT NULL CHECK (length(subject) BETWEEN 1 AND 256),
    issuer TEXT NOT NULL CHECK (issuer LIKE 'https://%'),
    authenticated_at BIGINT NOT NULL,
    expires_at BIGINT NOT NULL,
    csrf_hash BYTEA NOT NULL CHECK (octet_length(csrf_hash) = 32)
);
CREATE INDEX IF NOT EXISTS privi_sessions_issuer_subject_idx
    ON privi_sessions.sessions (issuer, subject);
CREATE INDEX IF NOT EXISTS privi_sessions_expires_idx
    ON privi_sessions.sessions (expires_at);
-- DBA: create a dedicated least-privilege application role, then grant
-- USAGE on schema and SELECT/INSERT/DELETE on this table only.
-- Do NOT grant access to public, billing schemas or payment tables.
-- Do NOT record cookies, raw handles, raw tokens, payment proof or PII.
