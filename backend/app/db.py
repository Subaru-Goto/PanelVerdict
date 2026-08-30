import psycopg

from app.config import settings


def check_connection() -> bool:
    """Return True if Postgres is reachable and answers a trivial query."""
    try:
        with (
            psycopg.connect(settings.database_url, connect_timeout=3) as conn,
            conn.cursor() as cur,
        ):
            cur.execute("SELECT 1")
            return cur.fetchone() == (1,)
    except psycopg.Error:
        return False
