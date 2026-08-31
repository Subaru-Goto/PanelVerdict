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

-- One row per paid request that passed the edge gate (045/#143): the rate
-- limiter counts a caller's rows inside the window before letting a run start.
-- In Postgres, not process memory, for the same reason the checkpointer is
-- (#144): a redeploy or a second worker must not forget the count. Rows older
-- than the widest window are dead weight; the limiter sweeps them
-- opportunistically on write.
CREATE TABLE IF NOT EXISTS request_ledger (
    endpoint     text NOT NULL,
    caller       text NOT NULL,                     -- the counted identity: the verified
                                                    -- subject id (/evaluate, /chat-caller),
                                                    -- thread id (/chat). Opaque by design
                                                    -- (063/#158) — the address it belongs
                                                    -- to lives in the provider's auth.users
                                                    -- and never in a table this app writes.
    requested_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS request_ledger_window_idx
    ON request_ledger (endpoint, caller, requested_at);

-- One row per paid request the gate admitted, priced at admission (064/#192).
-- The global daily cap sums the day's rows before admitting the next request.
-- `numeric`, so a day of additions stays exact at the cap boundary. Swept like
-- request_ledger: expired rows are deleted opportunistically on write.
CREATE TABLE IF NOT EXISTS spend_ledger (
    endpoint text NOT NULL,
    usd      numeric NOT NULL,
    spent_at timestamptz NOT NULL DEFAULT now()
);

-- One row per corpus chunk: the reader-facing explanations of what the report
-- *means*, retrieved by the analyst and shown with their citation (018/#124).
--
-- Regenerable from committed documents, so drop-and-reseed applies here as it
-- does to personas and not as it does to the votes ledger. There is deliberately
-- no foreign key and no ownership: the corpus is the same for every reader.
--
-- `search` is a generated tsvector rather than a maintained one, so a chunk's
-- keyword index cannot drift from its text — the reader's queries are exact
-- jargon ("HDI", "credible interval", "practical tie") where keyword match beats
-- embeddings, and the two are fused at query time.
CREATE TABLE IF NOT EXISTS corpus_chunks (
    id        text PRIMARY KEY,             -- "{document}#{heading}": stable when a section is added
    source    text NOT NULL,                -- the document title, as a reader would cite it
    section   text NOT NULL,                -- the heading this passage sits under
    passage   text NOT NULL,                -- heading + body: what was embedded and indexed
    embedding vector(1536) NOT NULL,        -- text-embedding-3-small dims, as personas
    search    tsvector GENERATED ALWAYS AS (to_tsvector('english', passage)) STORED
);

CREATE INDEX IF NOT EXISTS corpus_chunks_embedding_idx
    ON corpus_chunks USING hnsw (embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS corpus_chunks_search_idx
    ON corpus_chunks USING gin (search);


-- ---------------------------------------------------------------------------
-- Additive changes to tables that already exist (083/#173, 115/#248)
--
-- CREATE TABLE IF NOT EXISTS above accepts an out-of-date table without
-- altering it, so a column added to a table already deployed goes here — at the
-- bottom, in the order it was added, never by editing the CREATE above it. Two
-- reasons it must be here rather than in a separate file: this file is what
-- app.persistence.apply_schema runs, so the RLS sweep still fires afterwards;
-- and apply_schema reads its completeness probe out of these statements, so a
-- column added anywhere else is a column nothing checks for.
--
-- The form is required, and enforced by app.persistence._added_columns:
--
--     ALTER TABLE votes ADD COLUMN IF NOT EXISTS scored_at timestamptz;
--
-- IF NOT EXISTS because this file runs on every seed and every boot: a bare
-- ADD COLUMN succeeds once and fails forever after, taking the RLS sweep that
-- follows it down too.
--
-- Additive only. No DROP COLUMN, no type change, no rename — a reader of an
-- older deploy is still serving requests during a rollout, and votes is paid
-- model output that cannot be regenerated. A change that cannot be expressed
-- additively is a new column plus a backfill, and the old one left alone.
--
-- Nothing is pending: no table has outgrown its CREATE yet.
