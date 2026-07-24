-- Persona pool schema (006f D2). Idempotent: safe to run on every seed.
-- v1 uses raw DDL (no migration tool); migrations arrive with the v2 deploy.

CREATE EXTENSION IF NOT EXISTS vector;

-- One row per persona. Hard fields are SQL-filterable columns; Big Five are the
-- continuous sampled scores (levels are derived at render, never stored).
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

-- One row per (persona, interest): per-interest embeddings can't be an array
-- column (pgvector holds one vector per row). No vector index in v1 — that is a
-- search concern deferred to 012.
CREATE TABLE IF NOT EXISTS interests (
    persona_id text        NOT NULL REFERENCES personas(id) ON DELETE CASCADE,
    interest   text        NOT NULL,
    embedding  vector(1536) NOT NULL,             -- text-embedding-3-small dims
    PRIMARY KEY (persona_id, interest)
);
