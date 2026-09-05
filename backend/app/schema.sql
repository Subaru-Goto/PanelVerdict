-- Persona pool schema. Idempotent: safe to run on every seed.

CREATE EXTENSION IF NOT EXISTS vector;

-- One row per persona. Big Five are the continuous sampled scores; levels are
-- derived at render, never stored. Nothing here is a vector: the persona
-- embedding went with the search that read it (084/#175, dropped at the bottom
-- of this file), and the extension above now serves corpus_chunks alone.
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
    neuroticism       double precision NOT NULL
);

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


-- One row per finished test, stored for the account that ran it (117/#252).
-- The whole EvaluateResponse travels as JSONB rather than a normalised shape:
-- the sidebar reads two fields out of the document and the detail view reads it
-- whole, so a normalised shape would only ever be reassembled to render, and
-- every change to the response model would become a migration.
--
-- Deliberately unlike the other tables in one way: these rows are the
-- customer's own content — their headline text, and the phrases their audience
-- reading quoted — so DELETE /me deletes them. Every other table here holds
-- either regenerable data or an opaque id and a timestamp.
--
-- schema_version, not a bare document: pydantic tolerates an added field on
-- read but not a removed one, so without it an old row cannot be told apart
-- from a corrupt one.
CREATE TABLE IF NOT EXISTS tests (
    test_id        text PRIMARY KEY,            -- the run's own id, from run_vote_loop
    owner          text NOT NULL,               -- the verified subject id
    created_at     timestamptz NOT NULL DEFAULT now(),
    schema_version int  NOT NULL,
    report         jsonb NOT NULL               -- a dumped EvaluateResponse
);

-- The sidebar's only query: this owner's tests, newest first.
CREATE INDEX IF NOT EXISTS tests_owner_created_idx
    ON tests (owner, created_at DESC);

-- What a reader said about a report (053/#150). References the stored test and
-- cascades with it, so a delete — by test or by account — is a real delete and
-- no copy of the report's context survives in this table. The body's length is
-- bounded at the endpoint (schemas.FeedbackRequest, the chat message's bound),
-- not here, so the number lives in one place. Untrusted text: nothing reads it
-- into a prompt (docs/least-privilege.md).
CREATE TABLE IF NOT EXISTS feedback (
    feedback_id uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    owner       text        NOT NULL,             -- the verified subject id
    test_id     text        NOT NULL REFERENCES tests (test_id) ON DELETE CASCADE,
    body        text        NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);

-- The operator's only query: newest first (persistence.FEEDBACK_QUERY).
CREATE INDEX IF NOT EXISTS feedback_created_idx ON feedback (created_at DESC);


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
-- The form is required, and enforced by app.persistence._column_alterations:
--
--     ALTER TABLE votes ADD COLUMN IF NOT EXISTS scored_at timestamptz;
--
-- IF NOT EXISTS because this file runs on every seed and on every --schema-only
-- apply: a bare ADD COLUMN succeeds once and fails forever after, mid-file, so
-- the RLS sweep prepare_connection runs after it does not run either. (Not at
-- boot: the request path deliberately does not apply DDL — app/main.py.)
--
-- Additive by default. No type change and no rename, ever: neither can be made
-- idempotent, and a reader of an older deploy is still serving requests during
-- a rollout. A column may be DROPPED only when both of the reasons behind that
-- rule are satisfied in the negative (084/#175): (1) its last reader *and*
-- writer shipped and were *deployed* in an earlier PR, so no instance in a
-- rollout still touches it (a writer counts: the seed kept writing this
-- column for a deploy after nothing read it); and (2) its contents are
-- regenerable from git or cheap to recompute — never paid model output, which
-- is why `votes` can never qualify. (2) is enforced: _column_alterations
-- refuses a drop on any table outside `_REGENERABLE`. (1) is review's, and this
-- paragraph is what review checks against. A drop is written at the bottom of
-- this file as
--
--     DROP INDEX IF EXISTS <index>;
--     ALTER TABLE <table> DROP COLUMN IF EXISTS <column>;
--
-- so every apply converges. _column_alterations reads the ALTER exactly and
-- takes the column off the completeness probe; the DROP INDEX is not parsed —
-- a dropped column takes its indexes with it, so the line is legibility, not
-- correctness. A change that meets
-- neither test is a new column plus a backfill, and the old one left alone.
--
-- 086/#177 — the ledger is owner-scoped: a row is its buyer's, and the read
-- path matches within one owner or not at all. NOT NULL, because every paid
-- request has a verified subject id by the time it votes (092/#197 put the
-- form behind sign-in). The DEFAULT '' is not a live identity: it is what a
-- row gets when it predates this column, or when an older deploy writes one
-- mid-rollout — and the application refuses '' on both read and write, so
-- those rows are readable by no account, ever. Sweep rule (written with the
-- column, applied by a later ticket): a row is sweepable once a `tests` row
-- exists for its `test_id` — the stored report outlives the buffer — or once
-- its owner's account is gone, and a row under '' is sweepable on sight.
-- DELETE /me deliberately keeps these rows (they are opaque, and clearing
-- them would sell a still-valid token a fresh budget); the account being
-- gone is what makes them unreadable, and the sweep is what clears them.
ALTER TABLE votes ADD COLUMN IF NOT EXISTS owner_id text NOT NULL DEFAULT '';

-- `kept` (035/#136): every finished run is stored, because the analyst reads
-- the server's copy; the save cap decides whether the rail keeps the row. An
-- unkept row is readable by id under its owner until the on-write sweep takes
-- it. Rows from before the column are kept: they were only stored by choice.
ALTER TABLE tests ADD COLUMN IF NOT EXISTS kept boolean NOT NULL DEFAULT true;

-- The sweep's own index: it runs on every completion across all owners, and
-- the rail's index (owner, created_at) does not serve a scan for unkept rows.
CREATE INDEX IF NOT EXISTS tests_unkept_created_idx
    ON tests (created_at) WHERE NOT kept;

-- The persona vector (084/#175). `summary_embedding` served one analyst tool,
-- `search_personas`, retired and deployed in PR 1; the request path has read no
-- vector since (probed on a bare connection, 2026-09-04 — see `get_conn` in
-- app/main.py and its test). Regenerable: it was
-- the embedding of `persona_summary`'s rendered text, a cheap call over data the
-- seed still holds. Both tests of the rule above hold, so the column goes and
-- the pool seed makes no embedding call at all. The index first, by name — a
-- dropped column takes its indexes with it, but naming it keeps the intent
-- legible and the statement harmless on a database that never had it. Both
-- take ACCESS EXCLUSIVE on `personas` for the instant a catalogue change takes
-- (~200 rows, no rewrite), so a request reading the pool at that moment waits,
-- and nothing more.
DROP INDEX IF EXISTS personas_summary_embedding_idx;
ALTER TABLE personas DROP COLUMN IF EXISTS summary_embedding;
