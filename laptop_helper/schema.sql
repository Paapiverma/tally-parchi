-- ============================================================
-- Tally Parchi – Supabase Schema
-- Run this once in your Supabase SQL Editor.
-- ============================================================

-- Enable Row Level Security (RLS) — policies are added below.

-- ─── parchis ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS parchis (
    id            BIGSERIAL PRIMARY KEY,
    parchi_id     TEXT NOT NULL UNIQUE,   -- e.g. P-20260930-00142
    party         TEXT NOT NULL,
    date          TEXT NOT NULL,          -- DD-MM-YYYY as entered on phone
    status        TEXT NOT NULL DEFAULT 'PENDING',
                  -- PENDING | POSTING | SENT_TO_TALLY | FAILED | VOID
    error_message TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT status_check CHECK (
        status IN ('PENDING', 'POSTING', 'SENT_TO_TALLY', 'FAILED', 'VOID')
    )
);

-- ─── parchi_items ───────────────────────────────────────────
CREATE TABLE IF NOT EXISTS parchi_items (
    id          BIGSERIAL PRIMARY KEY,
    parchi_id   TEXT NOT NULL REFERENCES parchis(parchi_id) ON DELETE CASCADE,
    item_name   TEXT NOT NULL,
    qty         NUMERIC(10,3) NOT NULL,
    unit        TEXT NOT NULL
);

-- ─── masters ────────────────────────────────────────────────
-- Synced from Tally; consumed by phone dropdowns.
CREATE TABLE IF NOT EXISTS masters (
    id    BIGSERIAL PRIMARY KEY,
    type  TEXT NOT NULL,   -- PARTY | ITEM | UNIT
    name  TEXT NOT NULL,
    unit  TEXT             -- only relevant for ITEM rows
);

-- ─── Indexes ────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_parchis_status     ON parchis(status);
CREATE INDEX IF NOT EXISTS idx_parchi_items_ref   ON parchi_items(parchi_id);
CREATE INDEX IF NOT EXISTS idx_masters_type       ON masters(type);

-- ─── updated_at trigger ─────────────────────────────────────
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

CREATE OR REPLACE TRIGGER set_updated_at
BEFORE UPDATE ON parchis
FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- ─── Row Level Security ─────────────────────────────────────
ALTER TABLE parchis      ENABLE ROW LEVEL SECURITY;
ALTER TABLE parchi_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE masters      ENABLE ROW LEVEL SECURITY;

-- Authenticated users can read/write everything.
-- Tighten per user if needed.

CREATE POLICY "auth users full access" ON parchis
    FOR ALL TO authenticated USING (true) WITH CHECK (true);

CREATE POLICY "auth users full access" ON parchi_items
    FOR ALL TO authenticated USING (true) WITH CHECK (true);

CREATE POLICY "auth users full access" ON masters
    FOR ALL TO authenticated USING (true) WITH CHECK (true);

-- ─── Seed: one test parchi (delete after testing) ───────────
INSERT INTO parchis (parchi_id, party, date, status)
VALUES ('PARCHI-TEST-001', 'Sharma Safety Traders', '30-09-2026', 'PENDING')
ON CONFLICT DO NOTHING;

INSERT INTO parchi_items (parchi_id, item_name, qty, unit) VALUES
    ('PARCHI-TEST-001', 'ABC Fire Extinguisher 4 Kg', 3, 'Pcs'),
    ('PARCHI-TEST-001', 'ABC Fire Extinguisher 6 Kg', 2, 'Pcs')
ON CONFLICT DO NOTHING;
