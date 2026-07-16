-- Runs automatically on FIRST initialization of the Postgres data volume
-- (docker-entrypoint-initdb.d). For an already-initialized volume, apply
-- manually — see README.
CREATE EXTENSION IF NOT EXISTS vector;
