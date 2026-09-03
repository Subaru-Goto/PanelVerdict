"""Store the test the red-team's chat turns will be about (123/#289).

/chat reads the server's copy of a report and nothing the body claims
(035/#136), so before any attack can be sent the target needs one finished
test owned by the caller the harness will claim. The report is the test
factory's — built through the app's own models and arithmetic, over the
demo's two headlines — so the analyst has a real verdict to talk about.

Usage, from backend/ with POSTGRES_* pointing at the scratch database:

    uv run python -m experiments.red_team.seed_target [--owner red-team]

Prints the test id; the promptfoo config takes it as TEST_ID.
"""

from __future__ import annotations

import argparse
import asyncio
from uuid import uuid4

import psycopg

from app.config import settings
from app.demo import DEMO_CASES
from app.persistence import store_report

# The factory lives with the tests; it is the one place a report is built
# from votes rather than typed by hand. Importable because this runs as
# `python -m` from backend/.
from tests.factories import make_report


LOOPBACK = {"127.0.0.1", "localhost", "::1"}


async def seed(owner: str) -> str:
    # Scratch database only: a shell still holding the deployment's POSTGRES_*
    # would otherwise put a red-team row into the live table. The prose in the
    # README is not a guard; this is.
    if settings.postgres_host not in LOOPBACK:
        raise SystemExit(
            f"refusing to seed {settings.postgres_host!r}: the red-team target is a"
            " scratch database on this machine (POSTGRES_HOST=127.0.0.1)"
        )
    test_id = str(uuid4())
    report = make_report(variants=DEMO_CASES["save-half"])
    async with await psycopg.AsyncConnection.connect(settings.database_url) as conn:
        await store_report(conn, test_id=test_id, owner=owner, report=report)
        await conn.commit()
    return test_id


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--owner", default="red-team")
    args = parser.parse_args()
    print(asyncio.run(seed(args.owner)))


if __name__ == "__main__":
    main()
