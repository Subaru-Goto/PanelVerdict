-- Persona pool schema. Idempotent: safe to run on every seed.

CREATE EXTENSION IF NOT EXISTS vector;

-- One row per persona. Big Five are the continuous sampled scores; levels are
-- derived at render, never stored. summary_embedding is the vector the analyst's
-- panelist search matches against: one per persona, of the templated summary in
-- app/panel.py.
--
-- IF NOT EXISTS cannot migrate an out-of-date table; app.persistence.apply_schema
-- detects that case and says what to do.
CREATE TABLE IF NOT EXISTS personas (
    id                text PRIMARY KEY,           -- "{country}-{ordinal}", e.g. US-00042
    country           text NOT NULL,              -- Locale: US | JP | DE
    age               int  NOT NULL,
    gender            text NOT NULL,              -- male | female
    income_quintile   int  NOT NULL,              -- 1..5 within-country
    education         text NOT NULL,              -- EducationLevel enum value
    openness          double precision NOT NULL,
    conscientiousness double precision NOT NULL,
    extraversion      double precision NOT NULL,
    agreeableness     double precision NOT NULL,
    neuroticism       double precision NOT NULL,
    summary_embedding vector(1536) NOT NULL       -- text-embedding-3-small dims
);

-- Similarity index for the analyst's persona search. HNSW rather than IVFFlat:
-- IVFFlat trains its cluster centers from rows already present, and this file
-- runs before every seed — on an empty table it would build degenerate. The
-- opclass must match the search's `<=>` operator (cosine), or the planner
-- quietly ignores the index.
CREATE INDEX IF NOT EXISTS personas_summary_embedding_idx
    ON personas USING hnsw (summary_embedding vector_cosine_ops);

-- One row per vote ever paid for, keyed on the fingerprint of the exact question
-- asked (app/vote.py: vote_fingerprint), so a changed prompt, headline, question,
-- or model can never be served a stale answer. persona_id/test_id/order are
-- queryable provenance, not the key.
--
-- Append-only ledger: votes are paid model output — the one table NOT regenerable
-- from a seed — so the pool's drop-and-reseed convention does not apply. No
-- foreign key to personas for the same reason: reseeding the pool must
-- not cascade into the ledger.
CREATE TABLE IF NOT EXISTS votes (
    request_fingerprint text PRIMARY KEY,
    persona_id          text NOT NULL,
    test_id             text NOT NULL,               -- the run that paid for it
    chosen_variant_id   text NOT NULL,
    presentation_order  text[] NOT NULL,
    reason              text NOT NULL
);
