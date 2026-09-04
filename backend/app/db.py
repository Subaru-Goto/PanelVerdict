import psycopg

from app.config import settings

# Every connection this app opens waits this long for the pooler (112/#242).
# Evidence it is enough: the keep-warm ping opens a connection under it 120
# times a day and has to answer "db":"up" (keepalive.yml). When the pool is
# full the pooler queues a client for up to a minute (Supavisor FAQ, read
# 2026-09-04); a request learns in three seconds instead of waiting that out.
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
