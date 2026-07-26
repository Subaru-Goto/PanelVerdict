-- Persona pool schema. Idempotent: safe to run on every seed.

CREATE EXTENSION IF NOT EXISTS vector;

-- One row per persona. Big Five are the continuous sampled scores; levels are
-- derived at render, never stored. summary_embedding is the vector 007 retrieves
-- on: one per persona, of the templated summary in app/panel.py.
--
-- A database created before 006j has no summary_embedding column and a stale
-- interests table, and CREATE TABLE IF NOT EXISTS cannot fix either. Drop it and
-- reseed: the pool is a pure function of the master seed, so nothing is lost.
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
