import psycopg

from app.config import settings

# How long any connect on a path that must not hang waits for the pooler. Named
# rather than repeated: the health check and the startup Data API sweep are the
# two callers, and a boot that hangs and a health check that hangs are the same
# failure. The figure is the health check's own, unchanged.
CONNECT_TIMEOUT_SECONDS = 3


def check_connection() -> bool:
    """Return True if Postgres is reachable and answers a trivial query."""
    try:
        with (
            psycopg.connect(
                settings.database_url, connect_timeout=CONNECT_TIMEOUT_SECONDS
            ) as conn,
            conn.cursor() as cur,
        ):
            cur.execute("SELECT 1")
            return cur.fetchone() == (1,)
    except psycopg.Error:
        return False
